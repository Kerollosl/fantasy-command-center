from fastapi.testclient import TestClient
from ffcc.web.app import app

def test_pick_payload_rejected_before_board_load():
 c=TestClient(app)
 for body in [{"key":"x","slot":True},{"key":"x","slot":"2"},{"key":"","slot":1},{"key":"x","slot":0}]:
  assert c.post("/api/pick",json=body).status_code==422

def test_slot_payload_rejected_before_board_load():
 c=TestClient(app)
 for value in [None,0,True,"1",1.5]:
  assert c.post("/api/slot",json={"slot":value}).status_code==422
