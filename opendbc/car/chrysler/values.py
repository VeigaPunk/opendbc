import re
from enum import IntFlag
from dataclasses import dataclass, field

from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms, uds
from opendbc.car.structs import CarParams
from opendbc.car.docs_definitions import CarHarness, CarDocs, CarParts
from opendbc.car.fw_query_definitions import FwQueryConfig, LiveFwVersions, OfflineFwVersions, Request, p16

Ecu = CarParams.Ecu


class ChryslerSafetyFlags(IntFlag):
  RAM_DT = 1
  RAM_HD = 2


class ChryslerFlags(IntFlag):
  # Detected flags
  HIGHER_MIN_STEERING_SPEED = 1


@dataclass
class ChryslerCarDocs(CarDocs):
  package: str = "Adaptive Cruise Control (ACC)"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.fca]))


@dataclass
class ChryslerPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {
    Bus.pt: 'chrysler_pacifica_2017_hybrid_generated',
    Bus.radar: 'chrysler_pacifica_2017_hybrid_private_fusion',
  })


@dataclass(frozen=True)
class ChryslerCarSpecs(CarSpecs):
  minSteerSpeed: float = 3.8  # m/s


class CAR(Platforms):
  # Chrysler
  CHRYSLER_PACIFICA_2018_HYBRID = ChryslerPlatformConfig(
    [ChryslerCarDocs("Chrysler Pacifica Hybrid 2017-18")],
    ChryslerCarSpecs(mass=2242., wheelbase=3.089, steerRatio=16.2),
  )
  CHRYSLER_PACIFICA_2019_HYBRID = ChryslerPlatformConfig(
    [ChryslerCarDocs("Chrysler Pacifica Hybrid 2019-25")],
    CHRYSLER_PACIFICA_2018_HYBRID.specs,
  )
  CHRYSLER_PACIFICA_2018 = ChryslerPlatformConfig(
    [ChryslerCarDocs("Chrysler Pacifica 2017-18")],
    CHRYSLER_PACIFICA_2018_HYBRID.specs,
  )
  CHRYSLER_PACIFICA_2020 = ChryslerPlatformConfig(
    [
      ChryslerCarDocs("Chrysler Pacifica 2019-20"),
      ChryslerCarDocs("Chrysler Pacifica 2021-23", package="All"),
    ],
    CHRYSLER_PACIFICA_2018_HYBRID.specs,
  )

  # Dodge
  DODGE_DURANGO = ChryslerPlatformConfig(
    [ChryslerCarDocs("Dodge Durango 2020-21")],
    CHRYSLER_PACIFICA_2018_HYBRID.specs,
  )

  # Jeep
  JEEP_CHEROKEE_5TH_GEN = ChryslerPlatformConfig(
    [ChryslerCarDocs("Jeep Cherokee 2019-23")],
    ChryslerCarSpecs(mass=1747., wheelbase=2.70, steerRatio=17.0, minSteerSpeed=18.5),
    {Bus.pt: 'chrysler_cusw'},
  )
  JEEP_GRAND_CHEROKEE = ChryslerPlatformConfig(  # includes 2017 Trailhawk
    [ChryslerCarDocs("Jeep Grand Cherokee 2016-18", video="https://www.youtube.com/watch?v=eLR9o2JkuRk")],
    ChryslerCarSpecs(mass=1778., wheelbase=2.71, steerRatio=16.7),
  )

  JEEP_GRAND_CHEROKEE_2019 = ChryslerPlatformConfig(  # includes 2020 Trailhawk
    [ChryslerCarDocs("Jeep Grand Cherokee 2019-21", video="https://www.youtube.com/watch?v=jBe4lWnRSu4")],
    JEEP_GRAND_CHEROKEE.specs,
  )

  # Ram
  RAM_1500_5TH_GEN = ChryslerPlatformConfig(
    [ChryslerCarDocs("Ram 1500 2019-24", car_parts=CarParts.common([CarHarness.ram]))],
    ChryslerCarSpecs(mass=2493., wheelbase=3.88, steerRatio=16.3, minSteerSpeed=14.5),
    {Bus.pt: 'chrysler_ram_dt_generated'},
  )
  RAM_HD_5TH_GEN = ChryslerPlatformConfig(
    [
      ChryslerCarDocs("Ram 2500 2020-24", car_parts=CarParts.common([CarHarness.ram])),
      ChryslerCarDocs("Ram 3500 2019-22", car_parts=CarParts.common([CarHarness.ram])),
    ],
    ChryslerCarSpecs(mass=3405., wheelbase=3.785, steerRatio=15.61, minSteerSpeed=16.),
    {Bus.pt: 'chrysler_ram_hd_generated'},
  )


class CarControllerParams:
  def __init__(self, CP):
    self.STEER_STEP = 2  # 50 Hz
    self.STEER_ERROR_MAX = 80
    if CP.carFingerprint in RAM_HD:
      self.STEER_DELTA_UP = 14
      self.STEER_DELTA_DOWN = 14
      self.STEER_MAX = 361  # higher than this faults the EPS
    elif CP.carFingerprint in RAM_DT:
      self.STEER_DELTA_UP = 6
      self.STEER_DELTA_DOWN = 6
      self.STEER_MAX = 261  # EPS allows more, up to 350?
    elif CP.carFingerprint in CUSW_CARS:
      self.STEER_STEP = 1  # 100 Hz
      self.STEER_DELTA_UP = 4
      self.STEER_DELTA_DOWN = 4
      self.STEER_MAX = 250  # TODO: Some CUSW will go to 261, some not quite, exact boundaries not yet determined
    else:
      self.STEER_DELTA_UP = 3
      self.STEER_DELTA_DOWN = 3
      self.STEER_MAX = 261  # higher than this faults the EPS


STEER_THRESHOLD = 120

RAM_DT = {CAR.RAM_1500_5TH_GEN, }
RAM_HD = {CAR.RAM_HD_5TH_GEN, }
RAM_CARS = RAM_DT | RAM_HD
CUSW_CARS = {CAR.JEEP_CHEROKEE_5TH_GEN, }


CHRYSLER_VERSION_REQUEST = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER]) + \
  p16(0xf132)
CHRYSLER_VERSION_RESPONSE = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER + 0x40]) + \
  p16(0xf132)

CHRYSLER_SOFTWARE_VERSION_REQUEST = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER]) + \
  p16(uds.DATA_IDENTIFIER_TYPE.SYSTEM_SUPPLIER_ECU_SOFTWARE_NUMBER)
CHRYSLER_SOFTWARE_VERSION_RESPONSE = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER + 0x40]) + \
  p16(uds.DATA_IDENTIFIER_TYPE.SYSTEM_SUPPLIER_ECU_SOFTWARE_NUMBER)

CHRYSLER_RX_OFFSET = -0x280


# All Chrysler FW responses in the database are an 8 character part number followed by a
# 2 character revision, e.g. 68227902AF = part number 68227902 + revision AF.
# - Part number: identifies the physical part/software family. Changes for different platforms,
#    model years, and API breaks (e.g. JEEP_GRAND_CHEROKEE vs. JEEP_GRAND_CHEROKEE_2019 use
#    different part numbers on all platform code ECUs), so it must match for a fuzzy fingerprint.
# - Revision: bumped for minor software updates/recalls on the same part. Does not need to match,
#    allowing unseen firmware revisions of a seen platform to fuzzy fingerprint.
# Underscore is seen in one radar part number (22DTRHD_AA on RAM 1500)
CHRYSLER_FW_PATTERN = re.compile(b'^(?P<part>[A-Z0-9_]{8})(?P<revision>[A-Z0-9]{2})$')

# ECUs that are queried on all Chrysler platforms and report part numbers in the standard
# format, making them reliable for fuzzy fingerprinting:
# - combinationMeter: present on every platform, describes the cluster/generation
# - abs: present on all ICE platforms (hybrids can report it on an alternate address)
# - fwdRadar: describes the ACC radar/API generation
# - eps: describes the lateral API, differentiates model years such as Grand Cherokee 2016-18 vs. 2019-21
PLATFORM_CODE_ECUS = (Ecu.combinationMeter, Ecu.abs, Ecu.fwdRadar, Ecu.eps)


def get_platform_codes(fw_versions: list[bytes] | set[bytes]) -> set[bytes]:
  """Returns the part numbers (platform codes) from a list of FW versions, ignoring revisions."""
  codes = set()
  for fw in fw_versions:
    # FW responses can be padded with trailing spaces or null bytes
    match = CHRYSLER_FW_PATTERN.match(fw.rstrip(b'\x00 '))
    if match is not None:
      codes.add(match.group('part'))
  return codes


def match_fw_to_car_fuzzy(live_fw_versions: LiveFwVersions, vin: str, offline_fw_versions: OfflineFwVersions) -> set[str]:
  """Chrysler-specific fuzzy fingerprinting. Matches on part numbers only, ignoring the 2 character
  revision suffix, so cars with unseen firmware revisions of a seen platform still fingerprint.
  Since part numbers change on API breaks, cars with breaking changes correctly fail to match."""
  candidates: set[str] = set()

  for candidate, fws in offline_fw_versions.items():
    # Keep track of ECUs with a live part number present in the database for this candidate
    valid_found_ecus = set()
    valid_expected_ecus = {ecu[1:] for ecu in fws if ecu[0] in PLATFORM_CODE_ECUS}

    for ecu, expected_versions in fws.items():
      # Only check ECUs expected to report platform part numbers
      if ecu[0] not in PLATFORM_CODE_ECUS:
        continue

      addr = ecu[1:]
      expected_part_numbers = get_platform_codes(expected_versions)
      found_part_numbers = get_platform_codes(live_fw_versions.get(addr, set()))

      # Require the ECU to respond with a part number matching this candidate.
      # A missing or mismatching part number means a different platform or an API break
      if not any(found_part_number in expected_part_numbers for found_part_number in found_part_numbers):
        break

      valid_found_ecus.add(addr)

    # If all expected ECUs pass the part number check for candidate, add it as a match
    if len(valid_expected_ecus) and valid_expected_ecus.issubset(valid_found_ecus):
      candidates.add(candidate)

  return {str(c) for c in candidates}


FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    Request(
      [CHRYSLER_VERSION_REQUEST],
      [CHRYSLER_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.abs, Ecu.eps, Ecu.srs, Ecu.fwdRadar, Ecu.combinationMeter],
      rx_offset=CHRYSLER_RX_OFFSET,
      bus=0,
    ),
    Request(
      [CHRYSLER_VERSION_REQUEST],
      [CHRYSLER_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.abs, Ecu.hybrid, Ecu.engine, Ecu.transmission],
      bus=0,
    ),
    Request(
      [CHRYSLER_SOFTWARE_VERSION_REQUEST],
      [CHRYSLER_SOFTWARE_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.engine, Ecu.transmission],
      bus=0,
    ),
  ],
  extra_ecus=[
    (Ecu.abs, 0x7e4, None),  # alt address for abs on hybrids, NOTE: not on all hybrid platforms
  ],
  match_fw_to_car_fuzzy=match_fw_to_car_fuzzy,
)

DBC = CAR.create_dbc_map()
