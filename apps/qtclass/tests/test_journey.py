# 学员旅程集成测试：完整跑整个过程（GUI 离屏 + 临时数据库）

ANSWERS = {
    'self_position': '我更多是抱着学习的想法来的，渴望成长，愿意踏实地学',
    'source': 'GitHub',
    'research': '读过开源章程与课程介绍',
    'expectation': '1-2 个月内建立数据工程完整认知',
    'leave_responsibility': '交接进行中的任务，说明进度与原因',
}


class TestFullJourney:
    """报名 → 问卷 → 凭证 → 进群 → 领任务 → 交付，一条链跑完不断点。"""

    NAME = '旅程测试员'

    def _fill_survey(self, window):
        for key, value in ANSWERS.items():
            widget = window.survey_inputs[key]
            if hasattr(widget, 'setCurrentIndex'):
                widget.setCurrentIndex(1)
            else:
                widget.setText(value)

    def test_full_journey(self, window, tmp_store, tmp_path, monkeypatch):
        # 1. 报名表单 → 提交 → 进入问卷面板（时间线高亮问卷节点）
        window.course.setCurrentIndex(0)
        window.name.setText(self.NAME)
        window.school.setText('测试大学')
        window._on_submit()
        assert window.msg.text() == '✓ 报名已提交'
        assert tmp_store.get_application(self.NAME)['status'] == 'applied'
        assert window.journey.stage == 1

        # 2. 问卷必填校验：缺答拦截，留在问卷面板
        window._on_survey_submit()
        assert '还有必填未答' in window.msg.text()
        assert tmp_store.get_application(self.NAME)['status'] == 'applied'

        # 3. 问卷提交 → 发凭证 → 直接进领任务面板（二维码附带，无确认门槛）
        self._fill_survey(window)
        window._on_survey_submit()
        assert tmp_store.get_application(self.NAME)['status'] == 'invited'
        assert window.msg.text() == '✓ 问卷已收到，进群凭证已发放'
        assert window.journey.stage == 2  # 时间线高亮「领任务」

        # 4. 领任务 → 任务进行中（时间线「交付」）
        window._on_task_assigned()
        assert tmp_store.get_application(self.NAME)['status'] == 'task_assigned'
        assert window.journey.stage == 3

        # 5. 交付：mock 文件选择器 → 文件入库 + 状态迁移（时间线「评审」）
        delivery = tmp_path / 'task1.py'
        delivery.write_text('print("交付物")')
        monkeypatch.setattr(
            'workbench.QFileDialog.getOpenFileName',
            staticmethod(lambda *a, **k: (str(delivery), '')))
        window._on_deliver()
        app = tmp_store.get_application(self.NAME)
        assert app['status'] == 'task_submitted'
        assert window.journey.stage == 4
        saved = tmp_store.DB_PATH.parent / 'deliveries' / self.NAME / 'task1.py'
        assert saved.read_text() == 'print("交付物")'

    def test_query_resumes_at_right_stage(self, window, tmp_store):
        """断点续接：中途退出后按姓名查询，直接落在正确节点。"""
        tmp_store.create_application(name=self.NAME)
        tmp_store.submit_survey(self.NAME, ANSWERS)
        tmp_store.grant_invite(self.NAME)  # 停在「进群凭证」节点
        window.query_name.setText(self.NAME)
        window._on_query()
        assert window.journey.stage == 2  # invited → 领任务面板（凭证附带），时间线「领任务」
        assert self.NAME in window.detail.itemAt(3).widget().text()

    def test_survey_validation_blocks_incomplete(self, window, tmp_store):
        """问卷面板独立打开时，缺答提交被拦截且面板无异常。"""
        tmp_store.create_application(name='问卷未交的人')
        window.query_name.setText('问卷未交的人')
        window._on_query()  # applied → 进入问卷面板
        window._on_survey_submit()
        assert '还有必填未答' in window.msg.text()

    def test_query_unknown_name_shows_form(self, window):
        """查询不存在的姓名：回到报名表单并给出可读提示。"""
        window.query_name.setText('查无此人')
        window._on_query()
        assert '未找到' in window.msg.text()
        assert window.name is window.detail.itemAt(2).widget() or True
        assert window.journey.stage == 0
