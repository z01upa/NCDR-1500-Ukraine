import unittest
from decode_geography import FORMATS, BASE, decode_text, parse_regions, parse_cities, parse_aliases, parse_road_names
import struct

class NCDxDecoderTests(unittest.TestCase):
    def make_header_and_records(self, name, records):
        typ, stride, _ = FORMATS[name]
        header = bytearray(BASE)
        header[:7] = b"SIEMENS"
        header[47:60] = b"EU44420940.82"
        struct.pack_into('<HII', header, 84, typ, len(records), BASE + len(records)*stride)
        return bytes(header + b''.join(records))

    def test_text_accent(self):
        self.assertEqual(decode_text(b'LOUL\xc9\0\0'), 'LOULÉ')

    def test_link_city_region_and_bbox(self):
        region = bytearray(174)
        struct.pack_into('<H', region, 0, 0)
        region[30:34] = b'FARO'
        regions = parse_regions(self.make_header_and_records('CNY', [region]), {'records':1,'record_bytes':174})
        self.assertEqual(regions[0]['name'], 'FARO')
        city = bytearray(178)
        struct.pack_into('<iiii', city, 18, -824615,3713622,-824353,3713667)
        city[34:39] = b'PLACE'
        cities=parse_cities(self.make_header_and_records('CTY',[city]), {'records':1,'record_bytes':178}, regions)
        self.assertEqual(cities[0]['region_name'], 'FARO')
        self.assertEqual(cities[0]['lat_min'], 37.13622)
        self.assertEqual(cities[0]['lon_max'], -8.24353)

    def test_cl_city_alias_link(self):
        city = [{"name":"AACHEN"}]
        rec = bytearray(44)
        struct.pack_into('<I', rec, 0, 0)
        rec[4:6]=b'AI'
        rec[6:19]=b'X-LA-CHAPELLE'
        rows=parse_aliases(self.make_header_and_records('CL',[rec]), {"records":1,"record_bytes":44}, city)
        self.assertEqual(rows[0]['lookup_name'], 'AIX-LA-CHAPELLE')
        self.assertFalse(rows[0]['exact_city_name'])

    def test_rl_reference_candidate_sanity(self):
        rec=bytearray(61)
        struct.pack_into('<I',rec,0,4)
        rec[7:11]=b'ROAD'
        rows=parse_road_names(self.make_header_and_records('RL',[rec]),{"records":1,"record_bytes":61},5)
        self.assertEqual(rows[0]['name'], 'ROAD')
        self.assertEqual(rows[0]['ref_candidate_iof_index'], 4)
        with self.assertRaisesRegex(ValueError,'exceeds IOF'):
            parse_road_names(self.make_header_and_records('RL',[rec]),{"records":1,"record_bytes":61},4)

    def test_reject_bad_region(self):
        reg = {'region_id':0,'name':'FARO'}
        city = bytearray(178)
        struct.pack_into('<II',city,0,0,3)
        struct.pack_into('<iiii',city,18,-8_24615,37_13622,-8_24353,37_13667)
        city[34:35]=b'A'
        with self.assertRaisesRegex(ValueError,'missing CNY region'):
            parse_cities(self.make_header_and_records('CTY',[city]),{'records':1,'record_bytes':178},[reg])

if __name__ == '__main__':unittest.main()
