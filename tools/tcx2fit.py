import os
from tcxreader.tcxreader import TCXReader
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


class TCX2FITConverter:
    def __init__(self, tcx_path, fit_path, track_type="Run"):
        self.tcx_path = tcx_path
        self.fit_path = fit_path
        self.track_type = track_type

    def convert(self):
        try:
            # 使用 tcxreader 解析 TCX 文件
            tcx = TCXReader().read(self.tcx_path, only_gps=False)
            builder = FitFileBuilder(auto_define=True, min_string_size=50)

            # 动态推断运动类型
            sport_type = Sport.RUNNING
            sub_sport = SubSport.GENERIC
            if "Ride" in self.track_type or "Cycling" in self.track_type or tcx.activity_type == "Biking":
                sport_type = Sport.CYCLING
            elif "Hike" in self.track_type or "Walk" in self.track_type or tcx.activity_type == "Hiking":
                sport_type = Sport.HIKING

            # 提取所有带有时间的有效轨迹点
            points = []
            for lap in tcx.laps:
                for tp in lap.trackpoints:
                    if tp.time:
                        points.append(tp)

            if not points:
                return False

            first_point = points[0]
            last_point = points[-1]
            start_time_ms = int(first_point.time.timestamp() * 1000)
            end_time_ms = int(last_point.time.timestamp() * 1000)

            # 1. & 2. 写入 FileId 和 设备信息
            message = FileIdMessage()
            message.type = FileType.ACTIVITY
            message.manufacturer = 1
            message.product = 3415
            message.time_created = start_time_ms
            message.serial_number = 1234567890
            builder.add(message)

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
            total_calories = 0

            for lap in tcx.laps:
                # 累加卡路里 (TCX 中 Lap 包含卡路里)
                if hasattr(lap, 'calories') and lap.calories:
                    total_calories += lap.calories

                for tp in lap.trackpoints:
                    current_coordinate = None
                    if tp.latitude is not None and tp.longitude is not None:
                        current_coordinate = (tp.latitude, tp.longitude)
                    current_time = tp.time

                    if prev_coordinate and current_coordinate and prev_time and current_time:
                        delta = geodesic(prev_coordinate, current_coordinate).meters
                        time_diff = (current_time - prev_time).total_seconds()
                        if 0 < time_diff < 120:
                            moving_time += time_diff
                            # 如果 TCX 自带累计距离则用自带的，否则用计算的
                            if not hasattr(tp, 'distance') or tp.distance is None:
                                distance += delta

                    if hasattr(tp, 'distance') and tp.distance is not None:
                        distance = tp.distance

                    message = RecordMessage()
                    if current_coordinate:
                        message.position_lat = tp.latitude
                        message.position_long = tp.longitude

                    message.distance = distance
                    if hasattr(tp, 'elevation') and tp.elevation is not None:
                        message.altitude = tp.elevation
                    message.timestamp = int(tp.time.timestamp() * 1000)

                    # 提取心率
                    if hasattr(tp, 'hr_value') and tp.hr_value is not None:
                        message.heart_rate = int(tp.hr_value)

                    # 提取步频/踏频 (TCX 原生支持 Cadence)
                    if hasattr(tp, 'cadence') and tp.cadence is not None:
                        message.cadence = int(tp.cadence)

                    # 如果存在功率数据 (骑行)
                    if hasattr(tp, 'tpx_ext') and tp.tpx_ext and tp.tpx_ext.get('Watts'):
                        message.power = int(tp.tpx_ext.get('Watts'))

                    builder.add(message)

                    if current_coordinate:
                        prev_coordinate = current_coordinate
                    if current_time:
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
            if points[0].latitude:
                message.start_position_lat = points[0].latitude
                message.start_position_long = points[0].longitude
            if points[-1].latitude:
                message.end_position_lat = points[-1].latitude
                message.end_position_long = points[-1].longitude
            message.total_distance = distance
            if total_calories > 0:
                message.total_calories = int(total_calories)
            message.sport = sport_type
            message.sub_sport = sub_sport
            builder.add(message)

            # 7. Session 信息
            message = SessionMessage()
            message.timestamp = end_time_ms
            message.start_time = start_time_ms
            message.total_elapsed_time = total_elapsed_time
            message.total_timer_time = moving_time
            if points[0].latitude:
                message.start_position_lat = points[0].latitude
                message.start_position_long = points[0].longitude
            message.sport = sport_type
            message.sub_sport = sub_sport
            message.first_lap_index = 0
            message.num_laps = 1
            message.trigger = SessionTrigger.ACTIVITY_END
            message.event = Event.SESSION
            message.event_type = EventType.STOP
            message.total_distance = distance
            # 【关键】将汇总的卡路里写入 Session，这是佳明识别总消耗的关键！
            if total_calories > 0:
                message.total_calories = int(total_calories)
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
            print(f"TCX2FIT Conversion Error: {str(e)}")
            return False