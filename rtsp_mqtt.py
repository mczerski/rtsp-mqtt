#!/usr/bin/python3

import paho.mqtt.client as mqtt
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject
import sys
import socket
import argparse


class RtspMQTT:
    def __init__(self, brokerHost, brokerPort, rootTopic, rtspHost, rtspPort, alsaDevice):
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
        self._command = f'rtspsrc location=rtsp://{rtspHost}:{rtspPort}/test buffer-mode=4 ntp-sync=true ! rtpL16depay ! audioconvert ! audioresample ! alsasink device={alsaDevice}'
        self._pipeline_state = None
        
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
        elif payload == "0":
            self._rtsp_start_pipeline()

    def _send_mute(self, mute):
        topic = self._makeTopic('mute')
        payload = "1" if mute else "0"
        self._mqttClient.publish(topic, payload)

    def _clientStatus(self, _):
        mute = not (self._pipeline_state is not None and self._pipeline_state == Gst.State.PLAYING)
        self._send_mute(mute)

    def _rtsp_start_pipeline(self):
        self._pipeline = Gst.parse_launch(self._command)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._rtsp_on_message, None)
        self._pipeline.set_state(Gst.State.PLAYING)

    def _rtsp_stop_pipeline(self):
        self._pipeline.set_state(Gst.State.NULL)

    def _rtsp_on_message(self, bus, message, loop):
        """
            Gstreamer Message Types and how to parse
            https://lazka.github.io/pgi-docs/Gst-1.0/flags.html#Gst.MessageType
        """ 
        mtype = message.type
        if mtype == Gst.MessageType.STATE_CHANGED and message.src == self._pipeline:
            old, new, pending = message.parse_state_changed()
            self._pipeline_state = new
            if new == Gst.State.PLAYING:
                self._send_mute(False)
            elif old == Gst.State.PLAYING:
                self._send_mute(True)
        elif mtype == Gst.MessageType.EOS:
            # dHandle End of Stream
            print("End of stream")
            #TODO: this does not cause state change to not playing
            self._rtsp_stop_pipeline()
        elif mtype == Gst.MessageType.ERROR:
            # Handle Errors
            err, debug = message.parse_error() 
            print(err, debug) 
        elif mtype == Gst.MessageType.WARNING:
            # Handle warnings
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

parser = argparse.ArgumentParser()
parser.add_argument('--broker-host', default='localhost')
parser.add_argument('--broker-port', type=int, default=1883)
parser.add_argument('--rtsp-host', default='localhost')
parser.add_argument('--rtsp-port', type=int, default=8554)
parser.add_argument('--alsa-device', default='default')
args = parser.parse_args()

Gst.init(sys.argv)

rtsp_mqtt = RtspMQTT(
        brokerHost=args.broker_host,
        brokerPort=args.broker_port,
        rootTopic='snapcast',
        rtspHost=args.rtsp_host,
        rtspPort=args.rtsp_port,
        alsaDevice=args.alsa_device)

rtsp_mqtt.run()

