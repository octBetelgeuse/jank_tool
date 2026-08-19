from __future__ import annotations

import uiautomator2 as u2
import time
import os
from typing import Optional, Tuple, Any
from PIL import Image


class UiAutomatorManager:
    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id
        self.d = None
        self._connect()

    def _connect(self):
        _T0 = time.time()
        try:
            if self.device_id:
                self.d = u2.connect(self.device_id)
            else:
                self.d = u2.connect()
            _T_connect = time.time()
            try:
                self.d.settings['wait_timeout'] = 10
            except Exception:
                pass
            _T_done = time.time()
            print(f"[测速] uiautomator连接耗时: {_T_connect - _T0:.2f}s, "
                  f"设置耗时: {_T_done - _T_connect:.2f}s, "
                  f"总计: {_T_done - _T0:.2f}s")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to device: {e}")

    def reconnect(self):
        self._connect()

    def wait_for_package(self, package_name: str, timeout: int = 60):
        return self.d.wait(package_name, timeout=timeout)

    def wait_for_activity(self, activity_name: str, timeout: int = 60):
        return self.d.wait_activity(activity_name, timeout=timeout)

    def launch_app(self, package_name: str, wait: bool = True):
        """启动App
        
        Args:
            package_name: 包名或应用名
            wait: 是否等待App完全启动（True=慢但可靠，False=快但不等待）
        """
        self.d.app_start(package_name, wait=wait)

    def fast_launch_app(self, package_name: str):
        """快速启动App（不等待完全启动，适合负载操作场景）"""
        self.d.app_start(package_name, wait=False)

    def stop_app(self, package_name: str):
        self.d.app_stop(package_name)

    def clear_app_data(self, package_name: str):
        self.d.app_clear(package_name)

    def get_current_package(self) -> str:
        return self.d.current_package()

    def get_current_activity(self) -> str:
        return self.d.current_activity()

    def click(self, x: int, y: int):
        self.d.click(x, y)

    def click_element(self, resource_id: Optional[str] = None, text: Optional[str] = None,
                      text_contains: Optional[str] = None, className: Optional[str] = None,
                      description: Optional[str] = None, index: int = 0):
        if resource_id:
            self.d(resourceId=resource_id)[index].click()
        elif text:
            self.d(text=text)[index].click()
        elif text_contains:
            self.d(textContains=text_contains)[index].click()
        elif className:
            self.d(className=className)[index].click()
        elif description:
            self.d(description=description)[index].click()
        else:
            raise ValueError("At least one locator parameter must be provided")

    def long_click(self, x: int, y: int, duration: float = 1.0):
        self.d.long_click(x, y, duration)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, 
              duration: float = 0.5):
        self.d.swipe(start_x, start_y, end_x, end_y, duration=duration)

    def swipe_up(self, duration: float = 0.5, percent: float = 0.8):
        height = self.d.window_size()[1]
        start_y = int(height * percent)
        end_y = int(height * (1 - percent))
        self.d.swipe(500, start_y, 500, end_y, duration=duration)

    def swipe_down(self, duration: float = 0.5, percent: float = 0.8):
        height = self.d.window_size()[1]
        start_y = int(height * (1 - percent))
        end_y = int(height * percent)
        self.d.swipe(500, start_y, 500, end_y, duration=duration)

    def swipe_left(self, duration: float = 0.5, percent: float = 0.8):
        width = self.d.window_size()[0]
        start_x = int(width * percent)
        end_x = int(width * (1 - percent))
        self.d.swipe(start_x, 500, end_x, 500, duration=duration)

    def swipe_right(self, duration: float = 0.5, percent: float = 0.8):
        width = self.d.window_size()[0]
        start_x = int(width * (1 - percent))
        end_x = int(width * percent)
        self.d.swipe(start_x, 500, end_x, 500, duration=duration)

    def input_text(self, text: str, resource_id: Optional[str] = None):
        if resource_id:
            self.d(resourceId=resource_id).set_text(text)
        else:
            self.d.send_keys(text)

    def clear_text(self, resource_id: Optional[str] = None):
        if resource_id:
            self.d(resourceId=resource_id).clear_text()
        else:
            self.d.clear_text()

    def press_back(self):
        self.d.press('back')

    def press_home(self):
        self.d.press('home')

    def press_menu(self):
        self.d.press('menu')

    def press_enter(self):
        self.d.press('enter')

    def press_delete(self):
        self.d.press('delete')

    def press_volume_up(self):
        self.d.press('volume_up')

    def press_volume_down(self):
        self.d.press('volume_down')

    def press_power(self):
        self.d.press('power')

    def unlock_screen(self):
        self.d.unlock()

    def wake_up(self):
        self.d.wakeup()

    def get_element(self, resource_id: Optional[str] = None, text: Optional[str] = None,
                   text_contains: Optional[str] = None, className: Optional[str] = None,
                   description: Optional[str] = None, index: int = 0):
        if resource_id:
            return self.d(resourceId=resource_id)[index]
        elif text:
            return self.d(text=text)[index]
        elif text_contains:
            return self.d(textContains=text_contains)[index]
        elif className:
            return self.d(className=className)[index]
        elif description:
            return self.d(description=description)[index]
        return None

    def exists(self, resource_id: Optional[str] = None, text: Optional[str] = None,
               text_contains: Optional[str] = None, className: Optional[str] = None,
               description: Optional[str] = None) -> bool:
        if resource_id:
            return self.d(resourceId=resource_id).exists
        elif text:
            return self.d(text=text).exists
        elif text_contains:
            return self.d(textContains=text_contains).exists
        elif className:
            return self.d(className=className).exists
        elif description:
            return self.d(description=description).exists
        return False

    def wait_element(self, resource_id: Optional[str] = None, text: Optional[str] = None,
                     text_contains: Optional[str] = None, className: Optional[str] = None,
                     description: Optional[str] = None, timeout: int = 30) -> bool:
        if resource_id:
            return self.d(resourceId=resource_id).wait(timeout=timeout)
        elif text:
            return self.d(text=text).wait(timeout=timeout)
        elif text_contains:
            return self.d(textContains=text_contains).wait(timeout=timeout)
        elif className:
            return self.d(className=className).wait(timeout=timeout)
        elif description:
            return self.d(description=description).wait(timeout=timeout)
        return False

    def take_screenshot(self, output_path: str = "./screenshot.png"):
        self.d.screenshot(output_path)

    def dump_hierarchy(self, output_path: str = "./hierarchy.xml"):
        hierarchy = self.d.dump_hierarchy()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(hierarchy)

    def get_window_size(self) -> Tuple[int, int]:
        return self.d.window_size()

    def scroll(self, direction: str = "up", steps: int = 10):
        if direction == "up":
            for _ in range(steps):
                self.swipe_up()
                time.sleep(0.1)
        elif direction == "down":
            for _ in range(steps):
                self.swipe_down()
                time.sleep(0.1)
        elif direction == "left":
            for _ in range(steps):
                self.swipe_left()
                time.sleep(0.1)
        elif direction == "right":
            for _ in range(steps):
                self.swipe_right()
                time.sleep(0.1)

    def wait_for_idle(self, timeout: int = 10):
        self.d.wait_idle(timeout=timeout)

    def set_fastinput_ime(self, enable: bool = True):
        if enable:
            self.d.set_fastinput_ime(True)
        else:
            self.d.set_fastinput_ime(False)

    def hide_keyboard(self):
        self.d.hide_keyboard()

    def check_permission(self, permission: str) -> bool:
        return self.d.check_permission(permission)

    def grant_permission(self, permission: str):
        self.d.grant_permission(permission)

    def open_notification(self):
        self.d.open_notification()

    def open_quick_settings(self):
        self.d.open_quick_settings()

    def screenrecord(self, output_path: str = "./screenrecord.mp4", duration: int = 60):
        self.d.screenrecord(output_path, duration=duration)