import os
import gpxpy
from geopy.distance import geodesic
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.profile_type import (
  FileType, TimerTrigger, Event, EventType, Sport, SubSport, SessionTrigger, Activity
)


class GPX2FITConverter:
  def __init__(self, gpx_path, fit_path, track_type="Run"):
    self.gpx_path = gpx_path
    self.fit_path = fit_path
    self.track_type = track_type

  def convert(self):
    try:
      with open(self.gpx_path, 'r', encoding='utf-8') as f:
        gpx_data = gpxpy.parse(f)

      builder = FitFileBuilder(auto_define=True, min_string_size=50)

      # 1. 动态推断运动类型
      sport_type = Sport.RUNNING
      sub_sport = SubSport.GENERIC
      if "Ride" in self.track_type or "Cycling" in self.track_type:
        sport_type = Sport.CYCLING
      elif "Hike" in self.track_type or "Walk" in self.track_type:
        sport_type = Sport.HIKING

      # 2. 提取所有有效点
      points = []
      for track in gpx_data.tracks:
        for segment in track.segments:
          for track_point in segment.points:
            points.append(track_point)

      if not points:
        return False

      first_point = points[0]
      last_point = points[-1]

      start_time_ms = int(first_point.time.timestamp() * 1000)
      end_time_ms = int(last_point.time.timestamp() * 1000)

      # 1. 文件ID
      message = FileIdMessage()
      message.type = FileType.ACTIVITY
      message.manufacturer = 1
      message.product = 3415
      message.time_created = start_time_ms
      message.serial_number = 1234567890
      builder.add(message)

      # 2. 设备信息
      message = DeviceInfoMessage()
      message.serial_number = 1234567890
      message.manufacturer = 1
      message.garmin_product = 3415
      message.software_version = 3.58
      message.device_index = 0
      message.source_type = 5
      builder.add(message)

      # 3. 开始事件
      message = EventMessage()
      message.event = Event.TIMER
      message.event_type = EventType.START
      message.event_group = 0
      message.timer_trigger = TimerTrigger.MANUAL
      message.timestamp = start_time_ms
      builder.add(message)

      # 4. 记录点遍历
      distance = 0.0
      moving_time = 0.0
      prev_coordinate = None
      prev_time = None

      for track_point in points:
        current_coordinate = (track_point.latitude, track_point.longitude)
        current_time = track_point.time

        if prev_coordinate and prev_time:
          delta = geodesic(prev_coordinate, current_coordinate).meters
          time_diff = (current_time - prev_time).total_seconds()
          if 0 < time_diff < 120:
            moving_time += time_diff
            distance += delta

        message = RecordMessage()
        message.position_lat = track_point.latitude
        message.position_long = track_point.longitude
        message.distance = distance
        message.altitude = track_point.elevation
        message.timestamp = int(track_point.time.timestamp() * 1000)

        # 【修复】深度遍历 XML 节点获取心率和步频
        if track_point.extensions:
          for ext in track_point.extensions:
            # iter() 会递归遍历当前节点及其所有子节点，无视嵌套层级
            for node in ext.iter():
              if node.text and node.text.strip():
                tag_name = node.tag.lower()

                # 匹配心率 (hr, heartrate)
                if 'hr' in tag_name or 'heart' in tag_name:
                  try:
                    message.heart_rate = int(float(node.text.strip()))
                  except ValueError:
                    pass

                # 匹配步频/踏频 (cad, cadence, runcadence)
                elif 'cad' in tag_name:
                  try:
                    message.cadence = int(float(node.text.strip()))
                  except ValueError:
                    pass

        builder.add(message)

        prev_coordinate = current_coordinate
        prev_time = current_time

      total_elapsed_time = (last_point.time - first_point.time).total_seconds()

      # 5. 结束事件
      message = EventMessage()
      message.event = Event.TIMER
      message.event_type = EventType.STOP_ALL
      message.event_group = 0
      message.timer_trigger = TimerTrigger.MANUAL
      message.timestamp = end_time_ms
      builder.add(message)

      # 6. Lap 信息
      message = LapMessage()
      message.timestamp = end_time_ms
      message.start_time = start_time_ms
      message.total_elapsed_time = total_elapsed_time
      message.total_timer_time = moving_time
      message.start_position_lat = first_point.latitude
      message.start_position_long = first_point.longitude
      message.end_position_lat = last_point.latitude
      message.end_position_long = last_point.longitude
      message.total_distance = distance
      message.sport = sport_type
      message.sub_sport = sub_sport
      builder.add(message)

      # 7. Session 信息
      message = SessionMessage()
      message.timestamp = end_time_ms
      message.start_time = start_time_ms
      message.total_elapsed_time = total_elapsed_time
      message.total_timer_time = moving_time
      message.start_position_lat = first_point.latitude
      message.start_position_long = first_point.longitude
      message.sport = sport_type
      message.sub_sport = sub_sport
      message.first_lap_index = 0
      message.num_laps = 1
      message.trigger = SessionTrigger.ACTIVITY_END
      message.event = Event.SESSION
      message.event_type = EventType.STOP
      message.total_distance = distance
      builder.add(message)

      # 8. Activity 汇总信息
      message = ActivityMessage()
      message.timestamp = end_time_ms
      message.total_timer_time = moving_time
      message.num_sessions = 1
      message.type = Activity.MANUAL
      message.event = Event.ACTIVITY
      message.event_type = EventType.STOP
      builder.add(message)

      fit_file = builder.build()
      fit_file.to_file(self.fit_path)

      return True

    except Exception as e:
      import traceback
      traceback.print_exc()
      print(f"GPX2FIT Conversion Error: {str(e)}")
      return False
