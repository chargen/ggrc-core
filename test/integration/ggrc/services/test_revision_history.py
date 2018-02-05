# Copyright (C) 2018 Google Inc.
# Licensed under http://www.apache.org/licenses/LICENSE-2.0 <see LICENSE file>

"""Test for revision history api."""

import random
import json

import ddt
import sqlalchemy as sa

from ggrc.models import all_models
from ggrc import db

from integration.ggrc import TestCase
from integration.ggrc.api_helper import Api
from integration.ggrc.models import factories
from integration.ggrc_basic_permissions.models \
    import factories as rbac_factories

from appengine import base


@ddt.ddt
@base.with_memcache
class TestRevisionHistory(TestCase):
  """Test checks permissions for revision history."""

  def setUp(self):
    super(TestRevisionHistory, self).setUp()
    self.api = Api()
    roles = {r.name: r for r in all_models.Role.query.all()}
    ac_roles = {r.name: r for r in all_models.AccessControlRole.query.all()}
    with factories.single_commit():
      self.control = factories.ControlFactory()
      acrs = {
          "ACL_Reader": factories.AccessControlRoleFactory(
              name="ACL_Reader",
              object_type="Control",
              update=0),
          "ACL_Editor": factories.AccessControlRoleFactory(
              name="ACL_Editor",
              object_type="Control"),
      }
      self.program = factories.ProgramFactory()
      self.program.context.related_object = self.program
      self.relationship = factories.RelationshipFactory(
          source=self.program,
          destination=self.control,
          context=self.program.context,
      )
      self.people = {
          "Creator": factories.PersonFactory(),
          "Reader": factories.PersonFactory(),
          "Editor": factories.PersonFactory(),
          "Administrator": factories.PersonFactory(),
          "ACL_Reader": factories.PersonFactory(),
          "ACL_Editor": factories.PersonFactory(),
          "Program Editors": factories.PersonFactory(),
          "Program Managers": factories.PersonFactory(),
          "Program Readers": factories.PersonFactory(),
      }
      for role_name in ["Creator", "Reader", "Editor", "Administrator"]:
        rbac_factories.UserRoleFactory(role=roles[role_name],
                                       person=self.people[role_name])
      for role_name in ["Program Editors",
                        "Program Managers",
                        "Program Readers"]:
        person = self.people[role_name]
        rbac_factories.UserRoleFactory(role=roles["Creator"], person=person)
        factories.AccessControlListFactory(
            ac_role=ac_roles[role_name],
            object=self.program,
            person=self.people[role_name])
    with factories.single_commit():
      for role_name in ["ACL_Reader", "ACL_Editor"]:
        rbac_factories.UserRoleFactory(role=roles["Creator"],
                                       person=self.people[role_name])
        factories.AccessControlListFactory(
            ac_role=acrs[role_name],
            object=self.control,
            person=self.people[role_name])

  @ddt.data(
      ("Creator", True),
      ("Reader", False),
      ("Editor", False),
      ("ACL_Reader", False),
      ("ACL_Editor", False),
      ("Administrator", False),
      ("Program Editors", False),
      ("Program Managers", False),
      ("Program Readers", False),
  )
  @ddt.unpack
  def test_get(self, role_name, empty):
    """Test get revision history for {0}."""
    control_id = self.control.id
    query = all_models.Revision.query.filter(
        all_models.Revision.resource_id == control_id,
        all_models.Revision.resource_type == self.control.type,
    )
    if empty:
      ids = []
    else:
      ids = [i.id for i in query]
    self.api.set_user(self.people[role_name])
    self.client.get("/login")
    resp = self.api.client.get(
        "/api/revisions"
        "?resource_type=Control&resource_id={}".format(control_id)
    )
    self.assertEqual(
        ids,
        [i["id"] for i in resp.json["revisions_collection"]["revisions"]])

  def update_revisions(self, obj):
    """Assert revision diff between api and calculated in test.."""
    query = all_models.Revision.query.filter(
        all_models.Revision.resource_id == obj.id,
        all_models.Revision.resource_type == obj.type,
    ).order_by(
        sa.desc(all_models.Revision.updated_at)
    )
    diffs = [(i.id, json.loads(json.dumps(i.diff_with_current())))
             for i in query]
    for i in range(3):
      resp = self.api.client.get(
          "/api/revisions"
          "?__sort=-updated_at"
          "&resource_type={}"
          "&resource_id={}"
          "&_={}".format(
              obj.type,
              obj.id,
              random.randint(1100000000, 1153513123412)
          )
      )
      resp_diffs = [(i["id"], i["diff_with_current"])
                    for i in resp.json["revisions_collection"]["revisions"]]
      self.assertDictEqual(dict(diffs), dict(resp_diffs))
    self.assertFalse(any(resp_diffs[0][1].values()))

  def test_control_memcache(self):
    """Test get updated control revisions."""
    control_id = self.control.id
    self.api.put(self.control, {"title": "new_title"})
    self.control = all_models.Control.eager_query().get(control_id)
    self.update_revisions(self.control)
    db.session.expire_all()
    self.control = all_models.Control.eager_query().get(control_id)
    self.api.put(self.control, {"description": "new test description BLA"})
    self.control = all_models.Control.eager_query().get(control_id)
    self.update_revisions(self.control)
    self.api.put(self.control, {"description": "bla bla bla"})
    self.control = all_models.Control.eager_query().get(control_id)
    self.update_revisions(self.control)

  def test_risk_memcache(self):
    """Test get updated risk revisions."""
    risk = factories.RiskFactory()
    risk_id = risk.id
    self.api.put(risk, {"title": "new_title"})
    self.update_revisions(risk)
    db.session.expire_all()
    risk = all_models.Risk.eager_query().get(risk_id)
    self.api.put(risk, {"description": "new test description BLA"})
    risk = all_models.Risk.eager_query().get(risk_id)
    self.update_revisions(risk)
    risk = all_models.Risk.eager_query().get(risk_id)
    self.api.put(risk, {"description": "BLA bla bla"})
    risk = all_models.Risk.eager_query().get(risk_id)
    self.update_revisions(risk)