#!/usr/bin/python3

import paho.mqtt.client as mqtt
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject
from sysfs.gpio import Controller, OUTPUT
import os
import sys
import socket
import threading
import argparse
import contextlib
import json


class RtspMQTT:
    def __init__(self, brokerHost, brokerPort, rootTopic, rtspHost, rtspPort, alsaDevice, gpio):
        self._rootTopic = rootTopic
        self._hostname = socket.gethostname()
        self._mqttClient = mqtt.Client()
        self._mqttClient.on_connect = self._mqtt_on_connect
        self._mqttClient.on_message = self._mqtt_on_message
        self._brokerHost = brokerHost
        self._brokerPort = brokerPort
        self._rtspHost = rtspHost
        self._rtspPort = rtspPort
        self._alsaDevice = alsaDevice
        self._gpio = gpio
        self._command = f'rtspsrc location=rtsp://{rtspHost}:{rtspPort}/test buffer-mode=4 ntp-sync=true ! rtpL16depay ! audioconvert ! audioresample ! alsasink device={alsaDevice}'
        self._pipeline_state = None
        self._mute = True
        self._timer = threading.Timer(5, self._check_started)
        self._lock = threading.Lock()
        
        self._topicDispatcher = {
            "mute": self._clientMute,
            "status": self._clientStatus
        }
        self._quedRequests = {}

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        print('connected to [%s:%s] with result code %d' % (self._brokerHost, self._brokerPort, rc))
        topic = self._rootTopic + 'in/client/' + self._hostname + '/#'
        print('subscribing to: ' + topic)
        self._mqttClient.subscribe(topic)
        self._clientStatus(None)

    def _mqtt_on_message(self, client, obj, msg):
        with self._lock:
            payload = msg.payload.decode('utf-8')
            print ('received topic: %s. payload: %s' % (msg.topic, payload))
            parts = msg.topic.split("/")
            method = self._topicDispatcher.get(parts[-1], lambda payload: None)
            method(payload)

    def _makeTopic(self, *parts):
        return "/".join([self._rootTopic+'out', 'client', self._hostname] + list(parts))

    def _clientMute(self, payload):
        if payload == "1":
            self._rtsp_stop_pipeline()
            self._stop_timer()
        elif payload == "0":
            self._rtsp_start_pipeline()
            self._start_timer()

    def _send_mute(self):
        topic = self._makeTopic('mute')
        payload = "1" if self._mute else "0"
        self._mqttClient.publish(topic, payload)

    def _clientStatus(self, _):
        self._send_mute()

    def _rtsp_start_pipeline(self):
        self._pipeline = Gst.parse_launch(self._command)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._rtsp_on_message, None)
        self._pipeline.set_state(Gst.State.PLAYING)

    def _rtsp_stop_pipeline(self):
        self._pipeline.set_state(Gst.State.NULL)

    def _start_timer(self):
        self._timer = threading.Timer(5, self._check_started)
        self._timer.start()

    def _stop_timer(self):
        self._timer.cancel()

    def _check_started(self):
        playing = self._pipeline_state is not None and self._pipeline_state == Gst.State.PLAYING
        if not self._mute and not playing:
            self._rtsp_start_pipeline()
        if not self._mute:
            self._start_timer()

    def _rtsp_on_message(self, bus, message, loop):
        """
            Gstreamer Message Types and how to parse
            https://lazka.github.io/pgi-docs/Gst-1.0/flags.html#Gst.MessageType
        """ 
        with self._lock:
            mtype = message.type
            if mtype == Gst.MessageType.STATE_CHANGED and message.src == self._pipeline:
                old, new, pending = message.parse_state_changed()
                print(f'State changed from {old} to {new}')
                self._pipeline_state = new
                if new == Gst.State.PLAYING:
                    self._mute = False
                    self._gpio.set()
                    self._send_mute()
                elif old == Gst.State.PLAYING:
                    self._mute = True
                    self._gpio.reset()
                    self._send_mute()
            elif mtype == Gst.MessageType.EOS:
                print("end of stream")
                self._rtsp_stop_pipeline()
                self._rtsp_start_pipeline()
            elif mtype == Gst.MessageType.ERROR:
                err, debug = message.parse_error() 
                print(err, debug) 
            elif mtype == Gst.MessageType.WARNING:
                err, debug = message.parse_warning()
                print(err, debug)
      
            return True

    def run(self):
        self._mqttClient.connect_async(self._brokerHost, self._brokerPort)
        self._mqttClient.loop_start()

        loop = GObject.MainLoop()
        try:
            loop.run()
        except:
            self._mqttClient.loop_stop()
            raise

config = {
    'broker-host': 'localhost',
    'broker-port': 1883,
    'rtsp-host': 'localhost',
    'rtsp-port': 8554,
    'alsa-device': 'hw:0,0',
    'gpio-pin': 0
}
configPath = '/etc/rtsp-mqtt.json'
if os.path.exists(configPath):
    config.update(json.load(open(configPath)))

parser = argparse.ArgumentParser()
parser.add_argument('--broker-host', default=config.get('broker-host'))
parser.add_argument('--broker-port', type=int, default=config.get('broker-port'))
parser.add_argument('--rtsp-host', default=config.get('rtsp-host'))
parser.add_argument('--rtsp-port', type=int, default=config.get('rtsp-port'))
parser.add_argument('--alsa-device', default=config.get('alsa-device'))
parser.add_argument("--gpio-pin", type=int, default=config.get('gpio-pin'))
args = parser.parse_args()

Gst.init(sys.argv)
Controller.available_pins = [args.gpio_pin]

@contextlib.contextmanager
def speaker_gpio(gpio_pin):
    print(f'Allocing pin {gpio_pin}', sys.stderr)
    gpio = Controller.alloc_pin(gpio_pin, OUTPUT)
    try:
        yield gpio
    finally:
        print(f'Deallocing pin {gpio_pin}', sys.stderr)
        gpio.reset()
        Controller.dealloc_pin(gpio_pin)

with speaker_gpio(args.gpio_pin) as gpio:
    rtsp_mqtt = RtspMQTT(
            brokerHost=args.broker_host,
            brokerPort=args.broker_port,
            rootTopic='snapcast',
            rtspHost=args.rtsp_host,
            rtspPort=args.rtsp_port,
            alsaDevice=args.alsa_device,
            gpio=gpio)

    rtsp_mqtt.run()

