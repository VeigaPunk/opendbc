import unittest

import opendbc.safety.tests.common as common
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.common import make_msg


class Buttons:
  NONE = 0
  RESUME = 1
  SET = 2
  CANCEL = 4


PREV_BUTTON_SAMPLES = 8
ENABLE_BUTTONS = (Buttons.RESUME, Buttons.SET, Buttons.CANCEL)


class HyundaiButtonBase:
  BUTTONS_TX_BUS = 0  # tx on this bus, rx on 0
  SCC_BUS = 0  # rx on this bus

  def test_button_sends(self):
    """
      Only RES and CANCEL buttons are allowed
      - RES allowed while controls allowed
      - CANCEL allowed while cruise is enabled
    """
    self.safety.set_controls_allowed(0)
    self.assertFalse(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_TX_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_TX_BUS)))

    self.safety.set_controls_allowed(1)
    self.assertTrue(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_TX_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_TX_BUS)))

    for enabled in (True, False):
      self._rx(self._pcm_status_msg(enabled))
      self.assertEqual(enabled, self._tx(self._button_msg(Buttons.CANCEL, bus=self.BUTTONS_TX_BUS)))

  def test_enable_control_allowed_from_cruise(self):
    """
      Hyundai non-longitudinal only enables on PCM rising edge and recent button press. Tests PCM enabling with:
      - disallowed: No buttons
      - disallowed: Buttons that don't enable cruise
      - allowed: Buttons that do enable cruise
      - allowed: Main button with all above combinations
    """
    for main_button in (0, 1):
      for btn in range(8):
        for _ in range(PREV_BUTTON_SAMPLES):  # reset
          self._rx(self._button_msg(Buttons.NONE))

        self._rx(self._pcm_status_msg(False))
        self.assertFalse(self.safety.get_controls_allowed())
        self._rx(self._button_msg(btn, main_button=main_button))
        self._rx(self._pcm_status_msg(True))
        controls_allowed = btn in ENABLE_BUTTONS or main_button
        self.assertEqual(controls_allowed, self.safety.get_controls_allowed())

  def test_sampling_cruise_buttons(self):
    """
      Test that we allow controls on recent button press, but not as button leaves sliding window
    """
    self._rx(self._button_msg(Buttons.SET))
    for i in range(2 * PREV_BUTTON_SAMPLES):
      self._rx(self._pcm_status_msg(False))
      self.assertFalse(self.safety.get_controls_allowed())
      self._rx(self._pcm_status_msg(True))
      controls_allowed = i < PREV_BUTTON_SAMPLES
      self.assertEqual(controls_allowed, self.safety.get_controls_allowed())
      self._rx(self._button_msg(Buttons.NONE))


class HyundaiLongitudinalBase(common.LongitudinalAccelSafetyTest):

  DISABLED_ECU_UDS_MSG: tuple[int, int]
  DISABLED_ECU_ACTUATION_MSG: tuple[int, int]

  # set in subclasses for cars whose main button toggles cruise / have a pause-resume button
  MAIN_TOGGLE_CRUISE = False
  PAUSE_RESUME = False

  @classmethod
  def setUpClass(cls):
    if cls.__name__ == "HyundaiLongitudinalBase":
      cls.safety = None
      raise unittest.SkipTest

  # override these tests from CarSafetyTest, hyundai longitudinal uses button enable
  def test_disable_control_allowed_from_cruise(self):
    pass

  def test_enable_control_allowed_from_cruise(self):
    pass

  def test_sampling_cruise_buttons(self):
    pass

  def test_cruise_engaged_prev(self):
    pass

  def test_button_sends(self):
    pass

  def _pcm_status_msg(self, enable):
    raise Exception

  def _accel_msg(self, accel, aeb_req=False, aeb_decel=0):
    raise NotImplementedError

  def _enable_availability(self):
    """
      Press the main button (rising edge) so cruise becomes available, then store a
      set speed with SET. Resets controls allowed so tests start from a known state.
    """
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self._rx(self._button_msg(Buttons.NONE, main_button=0))
    self._rx(self._button_msg(Buttons.SET))
    self._rx(self._button_msg(Buttons.NONE))
    self.safety.set_controls_allowed(0)

  def test_set_resume_buttons(self):
    """
      SET and RESUME enter controls allowed on their falling edge, but only while
      cruise is available (main on) and a set speed has been stored.
    """
    self._enable_availability()
    for btn_prev in range(8):
      for btn_cur in range(8):
        self._rx(self._button_msg(Buttons.NONE))
        self.safety.set_controls_allowed(0)
        for _ in range(10):
          self._rx(self._button_msg(btn_prev))
          if self.PAUSE_RESUME:
            # pause/resume button toggles on its rising edge, reset for the next sample
            self.safety.set_controls_allowed(0)
          self.assertFalse(self.safety.get_controls_allowed())

        # should enter controls allowed on falling edge and not transitioning to cancel.
        # on pause/resume cars, a cancel rising edge toggles cruise back on
        should_enable = (btn_cur != btn_prev and
                         btn_cur != Buttons.CANCEL and
                         btn_prev in (Buttons.RESUME, Buttons.SET)) or \
                        (self.PAUSE_RESUME and btn_cur == Buttons.CANCEL and btn_prev != Buttons.CANCEL)

        self._rx(self._button_msg(btn_cur))
        self.assertEqual(should_enable, self.safety.get_controls_allowed())

  def test_main_button_availability_gate(self):
    """
      Main button is only a gate on cruise availability:
      - set/resume have no effect while cruise is unavailable (main off)
      - toggling main off disengages and blocks re-engagement
    """
    self.safety.set_controls_allowed(0)
    for btn in (Buttons.SET, Buttons.RESUME):
      self._rx(self._button_msg(btn))
      self._rx(self._button_msg(Buttons.NONE))
      self.assertFalse(self.safety.get_controls_allowed())

    # main rising edge makes cruise available; it does not engage except on cars
    # where the main button toggles cruise
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self.assertEqual(self.MAIN_TOGGLE_CRUISE, self.safety.get_controls_allowed())
    self._rx(self._button_msg(Buttons.NONE, main_button=0))

    # now set engages
    self._rx(self._button_msg(Buttons.SET))
    self._rx(self._button_msg(Buttons.NONE))
    self.assertTrue(self.safety.get_controls_allowed())

    # toggling main off disengages and blocks engagement again
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self._rx(self._button_msg(Buttons.NONE, main_button=0))
    self.assertFalse(self.safety.get_controls_allowed())
    for btn in (Buttons.SET, Buttons.RESUME):
      self._rx(self._button_msg(btn))
      self._rx(self._button_msg(Buttons.NONE))
      self.assertFalse(self.safety.get_controls_allowed())

  def test_resume_requires_set_speed(self):
    """
      Resume is not allowed if no cruise speed has been set since cruise became available.
    """
    # cruise available, no set speed: resume must not engage
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self._rx(self._button_msg(Buttons.NONE, main_button=0))
    self.safety.set_controls_allowed(0)  # main button itself may engage on toggle-cruise cars
    self._rx(self._button_msg(Buttons.RESUME))
    self._rx(self._button_msg(Buttons.NONE))
    self.assertFalse(self.safety.get_controls_allowed())

    # store a set speed: set engages
    self._rx(self._button_msg(Buttons.SET))
    self._rx(self._button_msg(Buttons.NONE))
    self.assertTrue(self.safety.get_controls_allowed())

    # cancel keeps the set speed, so resume is allowed again
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())
    self._rx(self._button_msg(Buttons.NONE))
    self._rx(self._button_msg(Buttons.RESUME))
    self._rx(self._button_msg(Buttons.NONE))
    self.assertTrue(self.safety.get_controls_allowed())

    # toggling main off clears the set speed: resume is blocked again
    for _ in range(2):
      self._rx(self._button_msg(Buttons.NONE, main_button=1))
      self._rx(self._button_msg(Buttons.NONE, main_button=0))
      self.safety.set_controls_allowed(0)  # main button itself may engage on toggle-cruise cars
    self._rx(self._button_msg(Buttons.RESUME))
    self._rx(self._button_msg(Buttons.NONE))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_cancel_button(self):
    self.safety.set_controls_allowed(1)
    self._rx(self._button_msg(Buttons.CANCEL))
    if not self.PAUSE_RESUME:
      self.assertFalse(self.safety.get_controls_allowed())
    else:
      # without cruise available, the pause/resume button does nothing
      self.assertTrue(self.safety.get_controls_allowed())
      # with cruise available and a set speed stored, it pauses
      self._enable_availability()
      self.safety.set_controls_allowed(1)
      self._rx(self._button_msg(Buttons.NONE))
      self._rx(self._button_msg(Buttons.CANCEL))
      self.assertFalse(self.safety.get_controls_allowed())

  def test_main_toggle_cruise_button(self):
    """
      On cars whose main button toggles cruise (MAIN_TOGGLE_CRUISE), the first rising
      edge of main enables cruise, and the next rising edge disables it.
    """
    if not self.MAIN_TOGGLE_CRUISE:
      raise unittest.SkipTest

    self.safety.set_controls_allowed(0)
    # first rising edge enables
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self.assertTrue(self.safety.get_controls_allowed())
    self._rx(self._button_msg(Buttons.NONE, main_button=0))
    self.assertTrue(self.safety.get_controls_allowed())
    # second rising edge disables
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_pause_resume_toggles_cruise(self):
    """
      On cars with a pause/resume button (PAUSE_RESUME), the cancel button toggles
      cruise on and off while cruise is available and a set speed is stored.
    """
    if not self.PAUSE_RESUME:
      raise unittest.SkipTest

    self._enable_availability()
    # resume
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertTrue(self.safety.get_controls_allowed())
    # holding the button must not oscillate
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertTrue(self.safety.get_controls_allowed())
    # pause on the next press
    self._rx(self._button_msg(Buttons.NONE))
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_pause_resume_disengages_after_main_engage(self):
    """
      Regression: after a main-button engage with no stored set speed, the pause
      direction of the pause/resume button must still disengage (engage-only gating
      on the stored set speed).
    """
    if not (self.MAIN_TOGGLE_CRUISE and self.PAUSE_RESUME):
      raise unittest.SkipTest

    # main button engages with no set speed stored
    self._rx(self._button_msg(Buttons.NONE, main_button=1))
    self.assertTrue(self.safety.get_controls_allowed())
    self._rx(self._button_msg(Buttons.NONE, main_button=0))
    # pause press must disengage even though no set speed was ever stored
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())
    # and it must not re-engage until a set speed is stored
    self._rx(self._button_msg(Buttons.NONE))
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_tester_present_allowed(self, ecu_disable: bool = True):
    """
      Ensure tester present diagnostic message is allowed to keep ECU knocked out
      for longitudinal control.
    """

    addr, bus = self.DISABLED_ECU_UDS_MSG
    for should_tx, msg in ((True, b"\x02\x3E\x80\x00\x00\x00\x00\x00"),
                           (False, b"\x03\xAA\xAA\x00\x00\x00\x00\x00")):
      tester_present = libsafety_py.make_CANPacket(addr, bus, msg)
      self.assertEqual(should_tx and ecu_disable, self._tx(tester_present))

  def test_disabled_ecu_alive(self):
    """
      If the ECU knockout failed, make sure the relay malfunction is shown
    """

    addr, bus = self.DISABLED_ECU_ACTUATION_MSG
    self.assertFalse(self.safety.get_relay_malfunction())
    self._rx(make_msg(bus, addr, 8))
    self.assertTrue(self.safety.get_relay_malfunction())
