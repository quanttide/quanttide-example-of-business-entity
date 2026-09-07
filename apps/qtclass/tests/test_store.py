# 学员河床状态机测试：数据层的每一步迁移与非法路径

import json


class TestStateMachine:
    """applied → survey_done → invited → in_group → task_assigned → task_submitted"""

    NAME = '状态机测试员'

    def _new_app(self, store):
        ok, err = store.create_application(name=self.NAME, school='测试大学',
                                           course='知识工作')
        assert ok, err

    def test_apply_creates_application(self, tmp_store):
        self._new_app(tmp_store)
        app = tmp_store.get_application(self.NAME)
        assert app['status'] == 'applied'
        assert app['school'] == '测试大学'
        assert app['survey_json'] is None
        assert app['applied_at']

    def test_duplicate_name_rejected(self, tmp_store):
        self._new_app(tmp_store)
        ok, err = tmp_store.create_application(name=self.NAME)
        assert not ok
        assert '已报名' in err

    def test_survey_transition_records_answers(self, tmp_store):
        self._new_app(tmp_store)
        answers = {'self_position': '学习成长', 'expectation': '学会数据工程'}
        ok, err = tmp_store.submit_survey(self.NAME, answers)
        assert ok, err
        app = tmp_store.get_application(self.NAME)
        assert app['status'] == 'survey_done'
        assert json.loads(app['survey_json']) == answers
        assert app['survey_at']

    def test_grant_invite(self, tmp_store):
        self._new_app(tmp_store)
        tmp_store.submit_survey(self.NAME, {'self_position': '学习成长'})
        ok, err = tmp_store.grant_invite(self.NAME)
        assert ok, err
        assert tmp_store.get_application(self.NAME)['status'] == 'invited'

    def test_mark_in_group(self, tmp_store):
        """进群确认：扫码后在工作台内点击（触发器在环内）。"""
        self._new_app(tmp_store)
        ok, err = tmp_store.mark_in_group(self.NAME)
        assert ok, err
        assert tmp_store.get_application(self.NAME)['status'] == 'in_group'

    def test_assign_task(self, tmp_store):
        self._new_app(tmp_store)
        ok, err = tmp_store.assign_task(self.NAME)
        assert ok, err
        assert tmp_store.get_application(self.NAME)['status'] == 'task_assigned'

    def test_submit_delivery(self, tmp_store):
        self._new_app(tmp_store)
        delivery = {'filename': 'task1.py', 'path': 'task1.py'}
        ok, err = tmp_store.submit_delivery(self.NAME, delivery)
        assert ok, err
        app = tmp_store.get_application(self.NAME)
        assert app['status'] == 'task_submitted'
        assert json.loads(app['delivery_json']) == delivery

    def test_full_state_chain(self, tmp_store):
        """整条链一气呵成，无断点。"""
        steps = [
            (lambda: tmp_store.create_application(name=self.NAME), 'applied'),
            (lambda: tmp_store.submit_survey(self.NAME, {'self_position': '学习成长'}), 'survey_done'),
            (lambda: tmp_store.grant_invite(self.NAME), 'invited'),
            (lambda: tmp_store.mark_in_group(self.NAME), 'in_group'),
            (lambda: tmp_store.assign_task(self.NAME), 'task_assigned'),
            (lambda: tmp_store.submit_delivery(self.NAME, {'filename': 'a.zip'}), 'task_submitted'),
        ]
        for run, status in steps:
            ok, err = run()
            assert ok, err
            assert tmp_store.get_application(self.NAME)['status'] == status

    def test_update_unknown_record(self, tmp_store):
        ok, err = tmp_store.assign_task('不存在的人')
        assert not ok
        assert '未找到报名记录' in err
