#!/usr/bin/env python
# coding=utf-8
from os import path
import time
import timeit
from collections import defaultdict
from pifx import PIFX
from fuzzywuzzy import fuzz
from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import getLogger

LOGGER = getLogger(__name__)

COLORS = {
    "blue": "#0000ff",
    "crimson": "#dc143c",
    "cyan": "#00ffff",
    "fuchsia": "#ff00ff",
    "gold": "#ffd700",
    "green": "#008000",
    "lavender": "#e6e6fa",
    "lime": "#00ff00",
    "magenta": "#ff00ff",
    "orange": "#ffa500",
    "pink": "#ffc0cb",
    "purple": "#800080",
    "red": "#ff0000",
    "salmon": "#fa8072",
    "sky blue": "#87ceeb",
    "teal": "#008080",
    "turquoise": "#40e0d0",
    "violet": "#ee82ee",
    "yellow": "#ffff00"
}

class LifxSkill(MycroftSkill):
    """
    A Mycroft skill for controlling Lifx devices via the HTTP API.
    """

    def __init__(self):
        super(LifxSkill, self).__init__(name="LifxSkill")
        # TODO Get the key from the the settingsmeta.json instead
        self.lifx = PIFX(self._get_key())

        # These will be set by _collect_devices
        self.lights = []
        self.lights_by_room = {}

    def initialize(self):
        self._collect_devices()

    def stop(self):
        pass

    @intent_handler(IntentBuilder("ConnectToLifxIntent")
        .require("LifxKeyword")
        .require("ConnectKeyword"))
    def handle_connect_to_lifx_intent(self, message):
        """
        Connect to Lifx, syncing up device data
        """
        self._collect_devices()
        self.speak_dialog("done")

    @intent_handler(IntentBuilder("ListLightsIntent")
        .require("ListRoom"))
    def handle_list_lights_intent(self, message):
        """
        List all of the lights in the default room or the named room
        """
        if message.data["ListRoom"] is "room" or message.data["ListRoom"] is "here":
            # TODO use settings to configure the default room for the device
            room = next(iter(self.lights_by_room))
        else:
            room = self._match_entity_to_group(message.data["ListRoom"])

        if room is None:
            self.speak("I am not sure what room {} is".format(message.data["ListRoom"]))
        else:
            self.speak("The lights in {} are".format(room))

            lights = self.lights_by_room[room]

            for light in lights:
                self.speak(light)
                # Toggle the light to point it out
                self.lifx.toggle_power(self._get_selector_for_entity(light))
                self.lifx.toggle_power(self._get_selector_for_entity(light))


    @intent_handler(IntentBuilder("SetPowerIntent")
        .require("LightAction")
        .require("Entity"))
    def handle_set_power_intent(self, message):
        """
        Turn lights on/off by name or room
        """
        state = message.data["LightAction"]
        entity = self._match_entity_to_known(message.data["Entity"])
        selector = self._get_selector_for_entity(entity)

        if "LightsStatement" in message.data:
            entity = "the {} lights".format(entity)

        results = self.lifx.set_state(selector=selector, power=state)

        if len(results) > 1:
            data = {
                "number": len(results),
                "room": entity,
            }
            self.speak_dialog("power.room." + state, data)
        else:
            data = {
                "light": entity,
            }
            self.speak_dialog("power.light." + state, data)

    @intent_handler(IntentBuilder("SetStateValueIntent")
        .require("SetKeyword")
        .one_of("WarmthKeyword", "BrightnessKeyword", "ColorKeyword")
        .require("Entity")
        .require("StateValue") )
    def handle_set_state_intent(self, message):
        """
        A single intent to handle setting the brightness, color and temperature
        """
        entity = self._match_entity_to_known(message.data["Entity"])
        state_value = message.data["StateValue"]

        if "BrightnessKeyword" in message.data:
            self._handle_set_brightness_intent(entity, state_value)
        elif "WarmthKeyword" in message.data:
            self._handle_set_temperature_intent(entity, state_value)
        elif "ColorKeyword" in message.data:
            self._handle_set_color_intent(entity, state_value)
        else:
            self.speak_dialog("whoops")

    def _handle_set_brightness_intent(self, entity, value):
        """
        Set the brightess of lights by name or room. The room should be a percentage of brightness
        """

        self.lifx.set_state(
            selector=self._get_selector_for_entity(entity),
            brightness=(float(value) / 100)
        )

        self.speak("Set {} to {} percent".format(entity, value))

    def _handle_set_temperature_intent(self, entity, value):
        """
        Set the temperature of lights by name or room.
        """
        selector = self._get_selector_for_entity(entity)

        if selector is None:
            self.speak("Unable to find the light or room {}".format(entity))
        else:
            self.lifx.set_state(
                selector=selector,
                color="kelvin:{}".format(value)
            )

            self.speak_dialog("done")

    def _handle_set_color_intent(self, entity, value):
        color_code = self._match_color(value)
        selector = self._get_selector_for_entity(entity)

        if color_code is None:
            self.speak("Cannot set the color {}".format(value))
        elif selector is None:
            self.speak("Could not find the light or room {}".format(entity))
        else:
            self.lifx.set_state(selector=selector, color=color_code)

            self.speak_dialog("done")

    def _match_entity_to_known(self, entity):
        """
        Find the closest matching known light/group to the entity
        """
        group = self._match_entity_to_group(entity)
        if group:
            return group

        light = self._match_entity_to_light(entity)
        if light:
            return light

        # TODO Return configured room instead
        return "all"

    def _get_selector_for_entity(self, entity):
        """
        Create a label for the given entity
        """
        for group, _ in self.lights_by_room.iteritems():
            if entity is group:
                return "group:" + group

        for light in self.lights:
            if entity is light:
                return "label:" + light

        # TODO Return configured room instead
        return "all"

    def _match_entity_to_group(self, entity):
        """
        Find the closest matching group to the entity
        """
        for group, _ in self.lights_by_room.iteritems():
            if fuzz.ratio(group, entity) > 70:
                return group

        return None

    def _match_entity_to_light(self, entity):
        """
        Find the closest matching light to the entity
        """
        for light in self.lights:
            if fuzz.ratio(light, entity) > 70:
                return light

        return None

    def _match_color(self, color):
        """
        Find the best match for the color requested
        """
        for name, code in COLORS.iteritems():
            if fuzz.ratio(name, color) > 70:
                return code

        return None

    def _get_key(self):
        key_file = open(path.join(path.abspath(path.dirname(__file__)), 'api_key'), 'r')
        key = key_file.read()
        key_file.close()

        return key

    def _collect_devices(self):
        # Reset light information
        self.lights_by_room = defaultdict(list)
        self.lights = []

        lights = self.lifx.list_lights()
        for light in lights:
            self.lights.append(light["label"])

            if light.get("group").get("name"):
                group = light.get("group").get("name")

                self.lights_by_room[group].append(light["label"])

def create_skill():
    """
    Initialize the skill
    """
    return LifxSkill()
