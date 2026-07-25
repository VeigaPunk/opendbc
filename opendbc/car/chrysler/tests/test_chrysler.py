import random
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.fw_versions import build_fw_dict
from opendbc.car.chrysler.fingerprints import FW_VERSIONS
from opendbc.car.chrysler.values import CAR, PLATFORM_CODE_ECUS, get_platform_codes, match_fw_to_car_fuzzy
from opendbc.testing import fuzzy_test

Ecu = CarParams.Ecu
CarFw = CarParams.CarFw


def build_live_fw(car_model, mutate_revision=False) -> list[CarFw]:
  """Builds a live FW list from a platform's database entry, optionally bumping
  the revision suffix to simulate an unseen firmware update."""
  car_fw = []
  for (ecu, addr, sub_addr), fw_versions in FW_VERSIONS[car_model].items():
    fw_version = random.choice(fw_versions)
    if mutate_revision and ecu in PLATFORM_CODE_ECUS:
      fw_version = fw_version.rstrip(b'\x00 ')
      fw_version = fw_version[:-2] + b'ZZ'  # revision not present anywhere in the database
    car_fw.append(CarFw(ecu=ecu, fwVersion=fw_version, brand='chrysler',
                        address=addr, subAddress=0 if sub_addr is None else sub_addr))
  return car_fw


class TestChryslerFingerprint(unittest.TestCase):
  def test_fw_format(self):
    # Asserts every FW version in the database parses into exactly one platform code (part number)
    for car_model, ecus in FW_VERSIONS.items():
      with self.subTest(car_model=car_model.value):
        for fws in ecus.values():
          for fw in fws:
            codes = get_platform_codes([fw])
            assert len(codes) == 1, f"Unable to parse FW: {fw}"
            assert len(list(codes)[0]) == 8, f"Bad part number: {fw}"

  def test_platform_codes_spot_check(self):
    # Standard format: 8 character part number + 2 character revision
    assert get_platform_codes([b'68227902AF']) == {b'68227902'}

    # Revisions of the same part number collapse to one code
    assert get_platform_codes([b'68227902AF', b'68227902AG', b'68227905AH']) == {b'68227902', b'68227905'}

    # FW responses can be padded with spaces or null bytes
    assert get_platform_codes([b'68267018AO ', b'68267018AO\x00\x00']) == {b'68267018'}

    # Non-standard FW versions are ignored
    assert get_platform_codes([b'AB', b'', b'68227902A', b'68227902ABC']) == set()

  @fuzzy_test(max_examples=100)
  def test_platform_codes_fuzzy_fw(self, fuzzy):
    get_platform_codes(fuzzy.list(fuzzy.binary))

  def test_platform_code_ecus_available(self):
    # Asserts enough ECUs with platform codes are available on all platforms for reliable matching
    for car_model, ecus in FW_VERSIONS.items():
      with self.subTest(car_model=car_model.value):
        present_ecus = {ecu[0] for ecu in ecus}
        platform_code_ecus = present_ecus & set(PLATFORM_CODE_ECUS)
        assert len(platform_code_ecus) >= 2, f"{car_model}: not enough platform code ECUs: {platform_code_ecus}"

        # combinationMeter and eps are present and unique to the platform on every car
        assert Ecu.combinationMeter in present_ecus
        assert Ecu.eps in present_ecus

  def test_fuzzy_matches_all_platforms(self):
    # Every platform must fuzzy fingerprint to exactly itself with all its FW versions present
    for car_model in FW_VERSIONS:
      with self.subTest(car_model=car_model.value):
        CP = CarParams(carFw=build_live_fw(car_model))
        matches = match_fw_to_car_fuzzy(build_fw_dict(CP.carFw), CP.carVin, FW_VERSIONS)
        assert matches == {str(car_model)}, f"{car_model}: got {matches}"

  def test_fuzzy_match_unseen_revision(self):
    # Fuzzy fingerprinting must work for unseen FW revisions of a seen platform
    for car_model in FW_VERSIONS:
      with self.subTest(car_model=car_model.value):
        for _ in range(5):
          CP = CarParams(carFw=build_live_fw(car_model, mutate_revision=True))
          matches = match_fw_to_car_fuzzy(build_fw_dict(CP.carFw), CP.carVin, FW_VERSIONS)
          assert matches == {str(car_model)}, f"{car_model}: got {matches}"

  def test_no_fuzzy_match_unseen_part_number(self):
    # A part number change (e.g. from a breaking API change on a new model year) must not fingerprint
    for car_model in FW_VERSIONS:
      with self.subTest(car_model=car_model.value):
        car_fw = build_live_fw(car_model)
        for fw in car_fw:
          if fw.ecu == Ecu.eps:
            fw.fwVersion = b'00000000AA'  # part number not in the database
        CP = CarParams(carFw=car_fw)
        matches = match_fw_to_car_fuzzy(build_fw_dict(CP.carFw), CP.carVin, FW_VERSIONS)
        assert len(matches) == 0, f"{car_model}: got {matches}"

  def test_no_fuzzy_match_wrong_part_numbers(self):
    # No match when no live part number exists in the database
    car_fw = [
      CarFw(ecu=Ecu.combinationMeter, fwVersion=b'99999999AA', brand='chrysler', address=0x742, subAddress=0),
      CarFw(ecu=Ecu.abs, fwVersion=b'99999998AA', brand='chrysler', address=0x747, subAddress=0),
      CarFw(ecu=Ecu.fwdRadar, fwVersion=b'99999997AA', brand='chrysler', address=0x753, subAddress=0),
      CarFw(ecu=Ecu.eps, fwVersion=b'99999996AA', brand='chrysler', address=0x75a, subAddress=0),
    ]
    CP = CarParams(carFw=car_fw)
    matches = match_fw_to_car_fuzzy(build_fw_dict(CP.carFw), CP.carVin, FW_VERSIONS)
    assert len(matches) == 0

  def test_no_fuzzy_match_missing_ecu(self):
    # Platforms must not match when one of their expected platform code ECUs is missing
    car_model = CAR.JEEP_GRAND_CHEROKEE_2019
    car_fw = [fw for fw in build_live_fw(car_model) if fw.ecu != Ecu.fwdRadar]
    CP = CarParams(carFw=car_fw)
    matches = match_fw_to_car_fuzzy(build_fw_dict(CP.carFw), CP.carVin, FW_VERSIONS)
    assert car_model not in matches, f"{car_model}: got {matches}"

  def test_empty_live_fw(self):
    assert len(match_fw_to_car_fuzzy({}, '', FW_VERSIONS)) == 0
