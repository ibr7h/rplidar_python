#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""

before run this code pls install parse library and also install construct lib for protocol

Copyright (c) 2016 Xu Zhihao (Howe).  All rights reserved.

This program is free software; you can redistribute it and/or modify

This programm is tested on kuboki base turtlebot.
"""

from reference import *
import serial
import numpy
import time
import rospy
import getpass
import collections
import math
import list_ports_linux
from sensor_msgs.msg import LaserScan
import copy

deque_len = 360
raw_data = collections.deque(maxlen=deque_len)
reset = False

class ClearParams:
    def __init__(self):
        rospy.logwarn('clearing parameters')
        rospy.delete_param('~scan_topic')
        rospy.delete_param('~rplidar_rate')
        rospy.delete_param('~rplidar_frame')
        rospy.delete_param('~range_min')
        rospy.delete_param('~range_max')

class driver:
    def stop_device(self):
        cmd = stop
        self.command(cmd)
        self.port.setDTR(1)
        self.port.close()

    def defination(self):
        global deque_len
        self.maxlen = deque_len
        self.ResponseType = {measurement: 'measurement', devinfo: 'devinfo', devhealth: 'devhealth'}
        self.ResponseStatus = {status_ok: 'status_ok', status_warning: 'status_warning', status_error: 'status_error'}
        self.ResponseMode = {SINGLE: 'SINGLE', MULTI: 'MULTI', UNDEFINED_f: 'UNDEFINED', UNDEFINED_s: 'UNDEFINED'}

        self.default_params()
        self.seq = 0
        self.accout = getpass.getuser()

        if not rospy.has_param('~scan_topic'):
            rospy.set_param('~scan_topic', '/scan')
        self.scan_topic = rospy.get_param('~scan_topic')
        # if not rospy.has_param('~rplidar_rate'):
        #     rospy.set_param('~rplidar_rate', 0.0001)
        # self.frequency = rospy.get_param('~rplidar_rate')
        if not rospy.has_param('~rplidar_port_name'):
            rospy.set_param('~rplidar_port_name', 'CP2102 USB to UART Bridge Controller')
        self.rplidar_port_name = rospy.get_param('~rplidar_port_name')
        if not rospy.has_param('~rplidar_frame'):
            rospy.set_param('~rplidar_frame', '/camera_depth_framer')
        self.rplidar_frame = rospy.get_param('~rplidar_frame')
        if not rospy.has_param('~range_min'):
            rospy.set_param('~range_min', 0.15)
        self.range_min = rospy.get_param('~range_min')
        if not rospy.has_param('~range_max'):
            rospy.set_param('~range_max', 6.0)
        self.range_max = rospy.get_param('~range_max')


    def port_finder(self, trigger):
        ports = list(list_ports_linux.comports())
        for port in ports:
            if self.rplidar_port_name in port[1]:
                trigger = True
                rospy.logwarn('find rplidar connect on port: %s' % port[0])
                return [port, trigger]
            else:
                # port = []
                trigger = False
        return [port, trigger]

    def __init__(self):
        self.defination()
        self.rplidar_matrix()
        self.start()

    def start(self, trigger=False, not_start=True):
        finder = self.port_finder(trigger)
        if finder[1]:
            self.port = serial.Serial("%s" % finder[0][0], 115200)
            self.port.setDTR(1)
            rospy.logwarn("connect port: %s" % finder[0][1])
            self.port.flushInput()  # discarding all flush input buffer contents
            self.port.flushOutput()
            health = self.device_health()
            try:
                rospy.loginfo('health status: %s'%self.ResponseStatus[health.status])
            except:
                rospy.logwarn('health status: %s' %health)
                self.start()
            if health != None:
                if health.status != status_ok:
                    self.driver_reset()
                else:
                    self.port.setDTR(0)
                    self.current = rospy.Time.now()
                    self.rplidar_points(not_start)
        else:
            rospy.loginfo('cannot find rplidar please connect rplidar on')
            self.stop_device()

    # 发送命令
    def command(self, com):
        rospy.loginfo('sending commands')
        command = com
        cmd = command_format.build(Container(sync_byte=sync_byte, cmd_flag=command))
        self.port.write(cmd)

    # 返回头字节
    def header_check(self):
        rospy.loginfo('evaluating header')
        stamp = time.time()
        time_out = 1
        # waiting for response
        while time.time() < stamp + time_out:
            if self.port.inWaiting() < response_header_format.sizeof():
                time.sleep(0.01)
            else:
                _str = self.port.read(response_header_format.sizeof())
                response_str = response_header_format.parse(_str)
                # rospy.loginfo('return data stream header checking result:\n')
                # rospy.loginfo('\ninitial response bytes(0XA5 0X5A): %s %s\n' % (hex(response_str.sync_byte1).upper(), hex(response_str.sync_byte2).upper()))
                # rospy.loginfo('response_size: %s'%hex(response_str.response.response_size))
                # rospy.loginfo('response_data: %s'%hex(response_str.response.response_data))
                # rospy.loginfo('response_mode: %s'%self.ResponseMode[response_str.response.response_mode])
                # rospy.loginfo('response_type: %s'%self.ResponseType[response_str.response_type])
                if response_str.sync_byte1 != sync_byte1 or response_str.sync_byte2 != sync_byte2:
                    rospy.logerr('unexpect response header')
                    return response_str.response_type
                    # os.system('rosnode kill cmd_tester')
                    # self.defination()
                    # self.rplidar_matrix()
                    # self.start()
                else:
                    return response_str.response_type
        rospy.loginfo("time out")


    # 硬件状态
    def device_health(self):
        # rospy.loginfo('device_health  %s' % hex(3))
        cmd = get_device_health
        self.command(cmd)
        if self.header_check() == devhealth:
            _str = self.port.readline(response_device_health_format.sizeof())
            response_str = response_device_health_format.parse(_str)
            # rospy.loginfo('rplidar device health:\n%s' % response_str)
            # rospy.loginfo('command for device health: %s' % hex(cmd))
            return response_str
        else:
            rospy.logwarn('command for devhealth error or return value error')
            return None

    # reset
    def driver_reset(self):
        cmd = reset
        self.command(cmd)
        self.port.setDTR(1)
        time.sleep(0.01)

    # start scanning
    def rplidar_matrix(self):
        self.frame = self.frame_default.copy()
        self.ranges = [i for i in self.ranges_default]
        # self.intensive = [i for i in self.intensive_default]

    def default_params(self):
        self.frame_default = {}
        self.ranges_default = []
        # self.intensive_default = []
        for i in range(360):
            self.frame_default['%s.0' % i] = []
            self.ranges_default.append(float('inf'))
            # self.intensive_default.append(0.0)

    def rplidar_points(self, not_start):
        cmd = scan
        self.command(cmd)
        if self.header_check() == measurement:
            while self.port.inWaiting() < response_device_point_format.sizeof():
                time.sleep(0.001)
            while not rospy.is_shutdown():
                global reset
                print 'loop'
                reset = False
                _str = self.port.read(response_device_point_format.sizeof())
                response = response_device_point_format.parse(_str)
                synbit = response.quality.syncbit
                syncbit_inverse = response.quality.syncbit_inverse
                # to start from a new circle
                if synbit and not_start:
                    not_start = False
                # fill up raw data
                if not not_start:
                    global raw_data
                    # release data
                    if synbit and not syncbit_inverse:
                        data_buff = list(raw_data)
                        raw_data.clear()
                        for i in range(len(data_buff)):
                            PolorCoordinate = self.OutputCoordinate(data_buff[i])
                            angle = PolorCoordinate[0]
                            if str(angle) in self.frame:
                                if not math.isinf(PolorCoordinate[1]):
                                    # self.intensive[int(angle)] = PolorCoordinate[2]
                                    self.frame[str(angle)].append(PolorCoordinate[1])
                                    self.ranges[int(angle)] = round(numpy.mean(self.frame[str(angle)]), 4)
                                    # self.frame[str(angle)].append(copy.deepcopy(PolorCoordinate[1]))
                                    # self.ranges[int(angle)] = round(numpy.mean(self.frame[str(angle)]), 4)

                        # self.lidar_publisher(copy.deepcopy(self.ranges), copy.deepcopy(self.intensive))
                        # ranges = [i for i in self.ranges]
                        self.lidar_publisher(self.ranges)
                        self.rplidar_matrix()
                    elif not synbit and syncbit_inverse:
                        self.rplidar_matrix()
                        pass
                    else:
                        rospy.logerr('buff error!!')
                        raw_data.clear()
                        if not reset:
                            reset=True
                            break
                    raw_data.append(_str)
                    # rospy.sleep(self.frequency)
            if reset:
                rospy.logwarn('resetting system')
                self.stop_device()
                self.rplidar_matrix()
                self.start()
        else:
            rospy.logerr('command for rplidar single scan error or return value error')
            self.rplidar_matrix()
            self.start()

    def OutputCoordinate(self, raw):
        response = response_device_point_format.parse(raw)
        inten = response.quality.quality
        angular = (response.angle_q6 >> angle_shift) / 64.0
        angle = round(angular)
        if response.distance_q2 != 0:
            dis = response.distance_q2 / 4.0 / 1000.0
        else:
            dis = float('inf')
        return [angle, dis, inten]

    def lidar_publisher(self, ranges, intensive = []):
        duration = (rospy.Time.now().secs - self.current.secs) + (rospy.Time.now().nsecs - self.current.nsecs) * (10 ** (-9))
        self.current = rospy.Time.now()
        # header
        _Scan = LaserScan()
        _Scan.header.stamp = rospy.Time.now()
        _Scan.header.seq = self.seq
        self.seq += 1
        _Scan.header.frame_id = self.rplidar_frame
        # rplidar_parameters
        _Scan.angle_max = numpy.pi - numpy.radians(0.0)
        _Scan.angle_min = numpy.pi - numpy.radians(360.0)
        _Scan.angle_increment = -numpy.radians(1.0)
        _Scan.time_increment = duration / 360
        _Scan.scan_time = duration
        _Scan.range_min = self.range_min
        _Scan.range_max = self.range_max
        # rplidar_ranges
        _Scan.ranges = ranges
        _Scan.intensities = intensive
        if _Scan != LaserScan():
            print 'pub'
            pub_data = rospy.Publisher(self.scan_topic, LaserScan, queue_size=1)
            pub_data.publish(_Scan)