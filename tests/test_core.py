import unittest
from core import (
    GROUPS, check_password, date_iso, uid_format, validate_dates, to_local_iso,
    visitor_info, create_payload, update_information_payload, update_reservation_payload
)

CFG={"entry_time":"09:00:00","exit_time":"17:00:00","valid_times":0}
REC={
    "appointID":"45", "appointStartTime":"2026-11-10T09:00:00-03:00",
    "appointEndTime":"2026-11-12T17:00:00-03:00",
    "visitReasonType":0, "visitReasonDetail":"",
    "visitorInfo":{"visitorGivenName":"Maria", "visitorFamilyName":"Silva",
                   "visitorGroupName":"Hóspedes Vale", "remark":"201", "visitorId":"3"}
}
class CoreTests(unittest.TestCase):
    def test_password(self):
        self.assertTrue(check_password("Ed31160561"))
        self.assertFalse(check_password("errada"))
    def test_dates(self):
        self.assertEqual(date_iso("12/11/2026"),"2026-11-12")
        self.assertRaises(ValueError,validate_dates,"12/11/2026","11/11/2026")
        self.assertEqual(to_local_iso("12/11/2026","17:00:00")[:19],"2026-11-12T17:00:00")
    def test_uid_endian(self):
        self.assertEqual(uid_format(bytes.fromhex("01 02 03 04"),"DECIMAL_LITTLE"),"67305985")
        self.assertEqual(uid_format(bytes.fromhex("01 02 03 04"),"DECIMAL_BIG"),"16909060")
        self.assertEqual(uid_format(bytes.fromhex("01 02"),"HEX_LITTLE"),"0201")
    def test_groups(self):
        self.assertEqual(GROUPS["Visitors"],"LOJA ACQUAVALE")
        self.assertRaises(ValueError,visitor_info,"A","B","1","Inexistente")
    def test_create(self):
        p=create_payload(CFG,"Ana","Teste","102","Hóspedes Vale","1234",b"fake",
                         "10/11/2026","12/11/2026")
        v=p["visitorInfoList"][0]["VisitorInfo"]
        self.assertEqual(v["cards"][0]["cardNo"],"1234")
        self.assertEqual(v["faces"][0]["faceData"],"ZmFrZQ==")
        self.assertEqual(p["appointStartTime"][:19],"2026-11-10T09:00:00")
    def test_edit_info_does_not_modify_dates(self):
        p=update_information_payload(REC,CFG,"José","Lima","301",
                         "Hóspedes Serra","",None)
        self.assertEqual(p["visitStartTime"],REC["appointStartTime"])
        self.assertEqual(p["visitEndTime"],REC["appointEndTime"])
        self.assertEqual(p["visitorInfoList"][0]["VisitorInfo"]["remark"],"301")
    def test_edit_reservation_does_not_rewrite_existing_person(self):
        p=update_reservation_payload(REC,CFG,"11/11/2026","13/11/2026")
        self.assertEqual(p["visitorInfoList"][0]["VisitorInfo"]["visitorGivenName"],"Maria")
        self.assertEqual(p["visitorInfoList"][0]["VisitorInfo"]["remark"],"201")
        self.assertEqual(p["appointEndTime"][:19],"2026-11-13T17:00:00")
    def test_missing_remote_data_blocks_update(self):
        self.assertRaises(ValueError,update_reservation_payload,{"appointID":"1"},CFG,"10/11/2026","11/11/2026")
if __name__=="__main__":
    unittest.main()
