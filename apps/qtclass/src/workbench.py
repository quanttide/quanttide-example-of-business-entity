# 量潮课堂工作台——河床架构参考实现（快照版）
# 本目录为独立样例：本地 SQLite 存储 + PySide6 界面，无外部服务依赖。

"""学员工作台 GUI：以考核进度时间线为中枢的单窗口应用。

信息架构：考核时间线常驻左侧作为主干，右侧详情面板永远是
「当前节点的动作」——报名表单就是「报名」节点的动作，
问卷/领任务/交付是主干上的后续节点，不设并列 Tab。

关键设计：

- 状态迁移全部是系统内事件（本地存储），无邮件、无外部服务
- 问卷为工作台内嵌表单，只问动机题；身份信息由报名一次采集
- 进群不设独立环节：问卷提交后凭证（二维码）直接附带在领任务面板，无确认门槛
- 领任务/交付 = 工作台内动作（学员点击、文件选择器），触发器不在环外

运行：python workbench.py（依赖 PySide6；无需任何配置）
"""

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

import store

# ---- 视觉体系 ----
PRIMARY = '#2F54EB'
PRIMARY_DARK = '#1D39C4'
BG = '#F5F7FA'
TEXT = '#262626'
MUTED = '#8C8C8C'
DONE = '#52C41A'
DANGER = '#F5222D'

QSS = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
#header {{ background: {PRIMARY}; }}
#brand {{ color: white; font-size: 18px; font-weight: 600; }}
#brandSub {{ color: #C9D4F7; font-size: 13px; }}
QFrame#card {{ background: white; border: 1px solid #EDEFF2; border-radius: 12px; }}
QLabel#title {{ font-size: 17px; font-weight: 600; background: transparent;
    border: none; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; background: transparent;
    border: none; }}
QLabel#muted, QLabel#fieldLabel {{ color: {MUTED}; font-size: 12px;
    background: transparent; border: none; }}
QLabel#desc {{ color: #595959; font-size: 13px; background: transparent;
    border: none; }}
QLabel#message {{ background: transparent; border: none; }}
QPushButton#primary {{ background: {PRIMARY}; color: white; border: none;
    border-radius: 8px; padding: 12px 16px; font-size: 14px; font-weight: 600; }}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ background: #9DB4F5; }}
QPushButton#ghost {{ background: white; color: {TEXT}; border: 1px solid #D9DEE7;
    border-radius: 8px; padding: 8px 14px; }}
QPushButton#ghost:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QLineEdit, QComboBox {{ background: white; border: 1px solid #D9DEE7;
    border-radius: 8px; padding: 9px 12px; font-size: 13px; color: {TEXT}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {PRIMARY}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
"""

# 课程目录（快照样例：结构与真实课程一致，内容为示例）
COURSES = [
    ('生产实习', '实训 · 报名入口课程'),
    ('知识工作', '入门'),
    ('氛围编程', '入门'),
    ('大数据导论', '进阶'),
    ('数据工程', '高阶'),
]

# 学员考核流程（脱胎于招聘考核：报名如投递，任务交付即考核，评审通过即发资格入基地）
ASSESSMENT = ['报名', '问卷', '领任务', '交付', '评审', '入册']

# 状态机状态 → 考核阶段索引
STATUS_STAGE = {
    'applied': 0,
    'survey_done': 1,
    'invited': 1,
    'task_assigned': 2,
    'task_submitted': 3,
    'reviewing': 3,
    'graded': 4,
    'enrolled': 5,
    'dormant': 0,
    'rejected': 0,
}

# 考核面板 → 时间线节点：面板以动作定义，时间线以考核节点高亮
# 如：面板 1（领任务，附带二维码）对应时间线「领任务」节点
STAGE_ASSESSMENT = {0: 0, 1: 2, 2: 3, 3: 4, 4: 5, 5: 5}

# 各考核节点的详情面板：标题 + 说明 + 动作列表 (文案, 类型, 参数)
# 类型：survey=内嵌问卷 / site=打开学习中心 / advance=学员确认推进 / deliver=工作台内交付
STAGE_DETAIL = {
    0: ('报名已提交',
        '完成准入问卷即可领取任务（7 天内完成，超时学习资格转休眠）。',
        [('填写准入问卷', 'survey', None)]),
    1: ('领取任务',
        '问卷已完成，入群二维码附在下方（7 天内有效）；扫码进群后，在学习中心浏览任务清单。',
        [('打开学习中心', 'site', None),
         ('已领到任务，标记进行中', 'advance', None)]),
    2: ('任务进行中',
        '按任务 deadline 完成后，在工作台直接提交交付物，交付即进入评审队列。',
        [('提交交付物', 'deliver', None)]),
    3: ('评审中',
        '交付物进入双人评审（代表初审 + 负责人终审），约 7 天出结论。',
        []),
    4: ('即将入册',
        '评估已定档，免费学员资格待确认。',
        []),
    5: ('已入册 🎉',
        '资格已生效，欢迎加入实训基地——之后的培养（实训、实习）在基地进行。',
        []),
}

# 准入问卷（内嵌表单；只问动机，身份信息由报名承载，不重复收集）
SURVEY_QUESTIONS = [
    ('self_position', '对自己做一个基本定位', 'select',
     ['我认为自己技术/专业能力已经比较过硬，有独立完成工作的信心',
      '我更多是抱着学习的想法来的，渴望成长，愿意踏实地学']),
    ('source', '您在哪里看到的招募信息', 'text', None),
    ('research', '在决定报名之前，你对课程做了哪些了解？请具体说说。',
     'text', None),
    ('expectation', '如果加入，你期望这段经历在未来1-2个月带给你最大的改变是什么？',
     'text', None),
    ('mismatch', '如果实际内容和你预想的有较大出入，你会怎么处理？',
     'text', None),
    ('leave_responsibility', '如果因某些原因决定离开，你觉得需要对团队和工作承担哪些责任？',
     'text', None),
]
SURVEY_REQUIRED = {'self_position', 'source', 'research', 'expectation',
                   'leave_responsibility'}
SURVEY_INTRO = ('我们寻找的不是「完美的螺丝钉」，而是坦诚、能对自己负责的同行者。\n'
                '请务必基于真实想法作答，没有标准答案。我们不接受美化、包装和撒谎。')

# 可选资产：入群二维码（放在 src/assets/group-qrcode.png 即显示；缺省降级为占位说明）
GROUP_QRCODE = Path(__file__).resolve().parent / 'assets' / 'group-qrcode.png'
LEARN_CENTER_URL = 'https://class.quanttide.com'


class AssessmentWidget(QWidget):
    """纵向考核时间线：圆点 + 连线，已完成/当前/未到三态。"""

    STEP_H, DOT_X, DOT_R = 52, 22, 7

    def __init__(self):
        super().__init__()
        self.stage = 0
        self.setMinimumWidth(180)
        self.setMinimumHeight(self.STEP_H * len(ASSESSMENT) + 24)

    def set_stage(self, stage: int):
        self.stage = stage
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        p.setFont(font)
        x, y = self.DOT_X, 20
        for i, step in enumerate(ASSESSMENT):
            if i < len(ASSESSMENT) - 1:
                pen = QPen(QColor(DONE if i < self.stage else '#E8E8E8'), 2)
                p.setPen(pen)
                p.drawLine(x, y + self.DOT_R, x, y + self.STEP_H - self.DOT_R)
            cy = y + i * self.STEP_H
            if i < self.stage:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(DONE))
                p.drawEllipse(x - self.DOT_R, cy - self.DOT_R,
                              self.DOT_R * 2, self.DOT_R * 2)
                p.setPen(QColor('white'))
                p.drawText(x - self.DOT_R, cy - self.DOT_R, self.DOT_R * 2,
                           self.DOT_R * 2, Qt.AlignCenter, '✓')
                p.setPen(QColor(MUTED))
                p.drawText(x + 20, cy - 11, 160, 22, Qt.AlignVCenter, step)
            elif i == self.stage:
                p.setPen(QPen(QColor(PRIMARY), 2))
                p.setBrush(QColor('white'))
                p.drawEllipse(x - self.DOT_R - 2, cy - self.DOT_R - 2,
                              self.DOT_R * 2 + 4, self.DOT_R * 2 + 4)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(PRIMARY))
                p.drawEllipse(x - 4, cy - 4, 8, 8)
                bold = QFont(font)
                bold.setBold(True)
                if font.pointSizeF() > 0:
                    bold.setPointSizeF(font.pointSizeF() + 1)
                p.setFont(bold)
                p.setPen(QColor(PRIMARY))
                p.drawText(x + 20, cy - 11, 160, 22, Qt.AlignVCenter, step)
                p.setFont(font)
            else:
                p.setPen(QPen(QColor('#E8E8E8'), 2))
                p.setBrush(QColor('white'))
                p.drawEllipse(x - self.DOT_R, cy - self.DOT_R,
                              self.DOT_R * 2, self.DOT_R * 2)
                p.setPen(QColor(MUTED))
                p.drawText(x + 20, cy - 11, 160, 22, Qt.AlignVCenter, step)
        p.end()


def clear_layout(layout):
    """递归清空布局内的控件与子布局。"""
    while (item := layout.takeAt(0)) is not None:
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif (sub := item.layout()) is not None:
            clear_layout(sub)
            sub.deleteLater()


class WorkbenchWindow(QMainWindow):
    """学员工作台：品牌栏 + 考核时间线（主干）+ 当前节点详情（动作面板）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('量潮课堂工作台')
        self.resize(820, 680)
        self._my_name = ''
        self._submitting = False
        self._build()
        self._show_form()  # 初始：报名节点动作 = 报名表单

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 品牌栏 + 身份切换（进度凭证 = 姓名）
        header = QWidget(objectName='header')
        header.setFixedHeight(56)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(24, 0, 24, 0)
        hlay.addWidget(QLabel('量潮课堂', objectName='brand'))
        hlay.addSpacing(8)
        hlay.addWidget(QLabel('工作台', objectName='brandSub'))
        hlay.addStretch()
        self.query_name = QLineEdit()
        self.query_name.setPlaceholderText('姓名（进度凭证）')
        self.query_name.setFixedWidth(180)
        self.query_name.returnPressed.connect(self._on_query)
        btn = QPushButton('查看进度', objectName='ghost')
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._on_query)
        hlay.addWidget(self.query_name)
        hlay.addWidget(btn)
        layout.addWidget(header)

        # 主干（时间线）+ 详情面板
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(32, 24, 32, 24)
        bl.setSpacing(20)

        assessment_card = QFrame(objectName='card')
        jl = QVBoxLayout(assessment_card)
        jl.setContentsMargins(20, 20, 8, 20)
        self.assessment = AssessmentWidget()
        jl.addWidget(self.assessment)
        jl.addStretch()
        bl.addWidget(assessment_card)

        self.detail_card = QFrame(objectName='card')
        self.detail = QVBoxLayout(self.detail_card)
        self.detail.setContentsMargins(28, 24, 28, 24)
        self.detail.setSpacing(8)
        bl.addWidget(self.detail_card, stretch=1)

        layout.addWidget(body, stretch=1)

    # ---- 详情面板：报名节点动作 = 报名表单 ----
    def _show_form(self):
        clear_layout(self.detail)
        self.assessment.set_stage(0)

        self.detail.addWidget(QLabel('开始你的学习', objectName='title'))
        self.detail.addWidget(QLabel('提交报名后完成准入问卷，即可扫码进群。',
                                     objectName='muted'))
        self.detail.addSpacing(10)

        def field(label, widget):
            self.detail.addWidget(QLabel(label, objectName='fieldLabel'))
            self.detail.addWidget(widget)

        self.course = QComboBox()
        self.course.addItems([f'{n}（{lv}）' for n, lv in COURSES])
        field('意向课程', self.course)

        self.name = QLineEdit()
        self.name.setPlaceholderText('请输入真实姓名')
        field('姓名', self.name)

        self.school = QLineEdit()
        self.school.setPlaceholderText('选填')
        field('学校', self.school)

        self.detail.addSpacing(10)
        self.btn_submit = QPushButton('提交报名，去填问卷', objectName='primary')
        self.btn_submit.setCursor(Qt.PointingHandCursor)
        self.btn_submit.clicked.connect(self._on_submit)
        self.detail.addWidget(self.btn_submit)

        self._add_msg()
        self.detail.addStretch()

    # ---- 详情面板：内嵌准入问卷（身份信息由报名承载，这里只问动机） ----
    def _show_survey(self, app: dict | None = None):
        clear_layout(self.detail)
        self.assessment.set_stage(1)  # 时间线高亮「问卷」节点

        self.detail.addWidget(QLabel('准入问卷', objectName='title'))
        intro = QLabel(SURVEY_INTRO, objectName='muted')
        intro.setWordWrap(True)
        self.detail.addWidget(intro)
        if app:
            who = ' · '.join(filter(None, [app['name'], app['school'], app['course']]))
            self.detail.addWidget(QLabel(f'以报名信息作答：{who}', objectName='muted'))
        self.detail.addSpacing(6)

        self.survey_inputs = {}

        def add_field(key, title, widget):
            lbl = QLabel(title + (' *' if key in SURVEY_REQUIRED else ''),
                         objectName='fieldLabel')
            lbl.setWordWrap(True)
            self.detail.addWidget(lbl)
            self.detail.addWidget(widget)

        for key, title, kind, options in SURVEY_QUESTIONS:
            if kind == 'select':
                combo = QComboBox()
                combo.addItem('请选择…')
                combo.addItems(options)
                self.survey_inputs[key] = combo
                add_field(key, title, combo)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText('请输入')
                self.survey_inputs[key] = edit
                add_field(key, title, edit)

        self.btn_survey = QPushButton('提交问卷', objectName='primary')
        self.btn_survey.setCursor(Qt.PointingHandCursor)
        self.btn_survey.clicked.connect(self._on_survey_submit)
        self.detail.addWidget(self.btn_survey)

        self._add_msg()
        self.detail.addStretch()

    # ---- 详情面板：考核各节点动作 ----
    def _show_stage(self, stage: int, note: str = ''):
        clear_layout(self.detail)
        self.assessment.set_stage(STAGE_ASSESSMENT.get(stage, stage))

        heading, desc, actions = STAGE_DETAIL.get(
            stage, (ASSESSMENT[stage], '联系课堂确认当前状态。', []))
        self.detail.addWidget(QLabel(heading, objectName='h2'))
        self.detail.addSpacing(2)
        d = QLabel(desc, objectName='desc')
        d.setWordWrap(True)
        self.detail.addWidget(d)
        if note:
            n = QLabel(note, objectName='muted')
            n.setWordWrap(True)
            self.detail.addWidget(n)

        # 进群凭证附带：问卷完成后二维码直接附在领任务面板（可选资产，缺省占位）
        if stage == 1:
            self.detail.addSpacing(8)
            if GROUP_QRCODE.exists():
                qr = QLabel()
                qr.setPixmap(QPixmap(str(GROUP_QRCODE)).scaledToWidth(
                    220, Qt.SmoothTransformation))
                qr.setAlignment(Qt.AlignCenter)
                self.detail.addWidget(qr)
            else:
                self.detail.addWidget(QLabel(
                    '（示例环境未放置二维码资产：把 group-qrcode.png 放入 '
                    'src/assets/ 即在此展示）', objectName='muted'))

        self.detail.addSpacing(10)
        for text, kind, arg in actions:
            b = QPushButton(text, objectName='primary' if kind == 'survey' else 'ghost')
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(220)
            if kind == 'survey':
                b.clicked.connect(self._continue_survey)
            elif kind == 'site':
                b.clicked.connect(self._open_site)
            elif kind == 'advance':
                b.clicked.connect(self._on_task_assigned)
            elif kind == 'deliver':
                b.clicked.connect(self._on_deliver)
            self.detail.addWidget(b)
        self._add_msg()
        self.detail.addStretch()

    # ---- 节点动作 ----
    def _continue_survey(self):
        app = store.get_application(self._my_name) if self._my_name else None
        self._show_survey(app)

    def _open_site(self):
        QDesktopServices.openUrl(QUrl(LEARN_CENTER_URL))

    def _on_task_assigned(self):
        ok, err = store.assign_task(self._my_name)
        if ok:
            self._show_stage(2)
        else:
            self._set_msg(f'⚠ {err}', DANGER)

    def _on_deliver(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择交付物')
        if not path:
            return
        dest_dir = store.DB_PATH.parent / 'deliveries' / self._my_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        shutil.copy2(path, dest)
        ok, err = store.submit_delivery(self._my_name, {
            'filename': dest.name, 'path': dest.name,
        })
        if ok:
            self._show_stage(3)
        else:
            self._set_msg(f'⚠ {err}', DANGER)

    # ---- 数据流 ----
    def _add_msg(self):
        """消息标签属于当前面板：随面板重建，避免悬空引用。"""
        self.msg = QLabel('', objectName='message')
        self.msg.setWordWrap(True)
        self.detail.addWidget(self.msg)

    def _set_msg(self, text, color=DONE):
        self.msg.setText(text)
        self.msg.setStyleSheet(f'color: {color}; font-size: 13px;')

    def _on_submit(self):
        if self._submitting:
            return
        name = self.name.text().strip()
        if not name:
            self._set_msg('⚠ 姓名必填——姓名是你的进度凭证', DANGER)
            return
        course = self.course.currentText().split('（')[0]  # 下拉带级别后缀，取回裸名
        ok, err = store.create_application(
            name=name, school=self.school.text().strip(), course=course)
        if not ok:
            self._set_msg(f'⚠ {err}', DANGER)
            return
        # 报名(applied) 完成 → 下一步动作 = 内嵌问卷；身份记住，进度免查询
        self._my_name = name
        self.query_name.setText(name)
        self._show_survey(store.get_application(name))
        self._set_msg('✓ 报名已提交')

    def _on_survey_submit(self):
        if self._submitting:
            return
        self._submitting = True
        answers, missing = {}, []
        for key, title, kind, _options in SURVEY_QUESTIONS:
            widget = self.survey_inputs[key]
            if kind == 'select':
                v = widget.currentText()
                v = '' if v == '请选择…' else v
            else:
                v = widget.text().strip()
            if key in SURVEY_REQUIRED and not v:
                missing.append(title)
            if v:
                answers[key] = v
        if missing:
            self._submitting = False
            self._set_msg('⚠ 还有必填未答：' + '；'.join(missing), DANGER)
            return
        ok, err = store.submit_survey(self._my_name, answers)
        if not ok:
            self._submitting = False
            self._set_msg(f'⚠ {err}', DANGER)
            return
        # 问卷提交 → 立即发凭证（系统内动作，无邮件）：提交与发凭证一气呢成
        ok2, err2 = store.grant_invite(self._my_name)
        self._submitting = False
        if not ok2:
            self._set_msg(f'⚠ {err2}', DANGER)
            return
        self._show_stage(1)
        self._set_msg('✓ 问卷已收到，进群凭证已发放')

    def _on_query(self):
        name = self.query_name.text().strip()
        if not name:
            return
        app = store.get_application(name)
        if app is None:
            self._show_form()
            self._set_msg(f'未找到 {name} 的报名记录——确认姓名与报名时一致，'
                          '或直接在下方提交报名', DANGER)
            return
        self._my_name = name
        stage = STATUS_STAGE.get(app['status'], 0)
        if stage == 0:  # 报名了但问卷未交：接着填问卷
            self._show_survey(app)
            self._set_msg('✓ 已找到你的报名记录，问卷还未完成')
        else:
            self._show_stage(stage, note=f'报名学员：{name}')


def main():
    app = QApplication([])
    font = QFont('Noto Sans CJK SC', 10)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)
    app.setStyleSheet(QSS)
    w = WorkbenchWindow()
    w.show()
    app.exec()


if __name__ == '__main__':
    main()
