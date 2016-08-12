# -*- coding: utf-8 -*-
"""Tests for cephlcm.common.models.server."""


import uuid

import pytest

from cephlcm.common.models import server


@pytest.mark.parametrize("state", (
    "op", "1", [], None, {}, object()
))
def test_set_state_fail(state):
    model = server.ServerModel()

    with pytest.raises(ValueError):
        model.state = state


@pytest.mark.parametrize("state", server.ServerModel.STATES)
def test_set_state_ok(state):
    model = server.ServerModel()

    model.state = state
    assert model.state == state


@pytest.mark.parametrize("state", server.ServerModel.STATES)
@pytest.mark.parametrize("facts", ({}, None, {"a": 1}))
@pytest.mark.parametrize("cluster_id", (None, str(uuid.uuid4())))
def test_create(state, facts, cluster_id, pymongo_connection,
                configure_model, freeze_time):
    name = pytest.faux.gen_alphanumeric()
    username = pytest.faux.gen_alphanumeric()
    fqdn = pytest.faux.gen_alphanumeric()
    ip = pytest.faux.gen_ipaddr()
    initiator_id = pytest.faux.gen_uuid()

    model = server.ServerModel.create(
        name, username, fqdn, ip, facts, cluster_id, state, initiator_id
    )

    assert model.name == name
    assert model.username == username
    assert model.fqdn == fqdn
    assert model.ip == ip
    assert model.facts == (facts or {})
    assert model.cluster_id == cluster_id
    assert model.state == state
    assert model.time_created == int(freeze_time.return_value)
    assert model.initiator_id == initiator_id
    assert model.time_deleted == 0
    assert model.version == 1

    db_model = pymongo_connection.db.server.find_one({"_id": model._id})

    assert model.name == db_model["name"]
    assert model.username == db_model["username"]
    assert model.fqdn == db_model["fqdn"]
    assert model.ip == db_model["ip"]
    assert model.facts == db_model["facts"]
    assert model.cluster_id == db_model["cluster_id"]
    assert model.state == db_model["state"]
    assert model.model_id == db_model["model_id"]
    assert model.time_created == db_model["time_created"]
    assert model.time_deleted == db_model["time_deleted"]
    assert model.initiator_id == db_model["initiator_id"]
    assert model.version == db_model["version"]


@pytest.mark.parametrize("facts", ({}, {"a": 1}))
@pytest.mark.parametrize("expand_facts", (True, False))
def test_make_api_structure(facts, expand_facts, configure_model):
    name = pytest.faux.gen_alphanumeric()
    username = pytest.faux.gen_alphanumeric()
    fqdn = pytest.faux.gen_alphanumeric()
    ip = pytest.faux.gen_ipaddr()
    initiator_id = pytest.faux.gen_uuid()

    model = server.ServerModel.create(name, username, fqdn, ip, facts,
                                      initiator_id=initiator_id)
    assert model.make_api_structure(expand_facts=expand_facts) == {
        "id": model.model_id,
        "model": server.ServerModel.MODEL_NAME,
        "time_updated": model.time_created,
        "time_deleted": model.time_deleted,
        "version": model.version,
        "initiator_id": initiator_id,
        "data": {
            "name": model.name,
            "username": model.username,
            "fqdn": model.fqdn,
            "ip": ip,
            "state": server.ServerModel.STATE_OPERATIONAL,
            "cluster_id": None,
            "facts": (facts if expand_facts else {})
        }
    }


def test_set_clusterid(configure_model):
    name = pytest.faux.gen_alphanumeric()
    username = pytest.faux.gen_alphanumeric()
    fqdn = pytest.faux.gen_alphanumeric()
    ip = pytest.faux.gen_ipaddr()
    initiator_id = pytest.faux.gen_uuid()

    model = server.ServerModel.create(name, username, fqdn, ip, {},
                                      initiator_id=initiator_id)
    cluster_id1 = pytest.faux.gen_uuid()
    model.cluster = cluster_id1
    model.save()

    cluster_id2 = pytest.faux.gen_uuid()
    with pytest.raises(ValueError):
        model.cluster = cluster_id2

    model.cluster = None
    model.save()

    model.cluster = cluster_id2
    model.save()


def test_delete_if_cluster_id_set(configure_model):
    name = pytest.faux.gen_alphanumeric()
    username = pytest.faux.gen_alphanumeric()
    fqdn = pytest.faux.gen_alphanumeric()
    ip = pytest.faux.gen_ipaddr()
    initiator_id = pytest.faux.gen_uuid()
    cluster_id = pytest.faux.gen_uuid()

    model = server.ServerModel.create(name, username, fqdn, ip, {},
                                      initiator_id=initiator_id,
                                      cluster_id=cluster_id)

    # TODO(Sergey Arkhipov): Put proper exception here
    with pytest.raises(Exception):
        model.delete()

    model.cluster = None
    model.save()

    model.delete()
