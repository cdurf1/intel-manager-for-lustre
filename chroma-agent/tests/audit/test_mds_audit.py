import os
from chroma_agent.device_plugins.audit.lustre import MdsAudit

from tests.test_utils import PatchedContextTestCase


class TestMdsAudit(PatchedContextTestCase):
    """Test MDS audit for 1.8.x filesystems; unused on 2.x filesystems"""
    def test_audit_is_available(self):
        """Test that MDS audits happen for 1.8.x audits."""
        tests = os.path.join(os.path.dirname(__file__), '..')
        self.test_root = os.path.join(tests, "data/lustre_versions/1.8.7.80/mds_mgs")
        super(TestMdsAudit, self).setUp()
        self.assertTrue(MdsAudit.is_available())

    def test_mdd_obd_skipped(self):
        """Test that the mdd_obd device is skipped for 2.x audits (HYD-437)"""
        tests = os.path.join(os.path.dirname(__file__), '..')
        self.test_root = os.path.join(tests, "data/lustre_versions/2.0.66/mds_mgs")
        super(TestMdsAudit, self).setUp()
        self.assertFalse(MdsAudit.is_available())
