"""Regression: a user with a metrics-written last_online must not 500 the list.

The metrics job stores a datetime on User.last_online while the API contract
is an ISO string (or null). serialize() validates the ORM row BEFORE
overwriting the field, so the first user to come online 500ed GET /users/
for everyone. The Users schema now coerces datetime -> ISO string.
"""

import datetime as dt

from backend.schema import Users


def _row(**kw):
    base = {
        "id": 44,
        "name": "uip_regression",
        "is_active": True,
        "total": None,
        "used": 0,
        "max_logins": 1,
        "expiry_date": dt.date(2030, 1, 1),
        "owner": "test_admin",
        "uuid": "00000000-0000-4000-8000-000000000000",
        "last_online": None,
    }
    base.update(kw)
    return type("Row", (), base)()


def test_last_online_none_ok():
    assert Users.model_validate(_row()).model_dump()["last_online"] is None


def test_last_online_datetime_coerced():
    item = Users.model_validate(_row(last_online=dt.datetime(2026, 9, 13, 22, 55, 0, 71291))).model_dump()
    assert item["last_online"] == "2026-09-13T22:55:00.071291"


def test_last_online_string_passthrough():
    item = Users.model_validate(_row(last_online="2026-09-13T22:55:00")).model_dump()
    assert item["last_online"] == "2026-09-13T22:55:00"


def test_users_schema_exposes_id_for_newest_first_sort():
    from backend.schema import Admins, Users

    assert Users.model_validate(_row()).id == 44
    assert Admins.model_validate({"id": 7, "username": "a"}).id == 7
