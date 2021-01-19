from atlas.conditions import (
    true, false, ParamExists
)
from atlas import session

def test_true():
    assert bool(true)

def test_false():
    assert not bool(false)

def test_params():
    
    cond = ParamExists(mode="test", state="right")

    assert not bool(cond)
    session.parameters["mode"] = "test"
    
    assert not bool(cond)
    session.parameters["state"] = "wrong"

    assert not bool(cond)
    session.parameters["state"] = "right"

    assert bool(cond)