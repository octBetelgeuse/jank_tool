import time
from jank_test_tool import JankTestTool


def scroll_test(uiautomator):
    for i in range(10):
        print(f"Scrolling {i+1}/10")
        uiautomator.swipe_up(duration=0.5)
        time.sleep(1)


def app_navigation_test(uiautomator):
    print("Testing app navigation...")
    
    uiautomator.swipe_up()
    time.sleep(1)
    
    uiautomator.swipe_up()
    time.sleep(1)
    
    uiautomator.press_back()
    time.sleep(1)
    
    uiautomator.swipe_down()
    time.sleep(1)


def complex_ui_test(uiautomator):
    print("Running complex UI test...")
    
    for _ in range(3):
        uiautomator.swipe_up()
        time.sleep(0.5)
    
    if uiautomator.exists(text="Settings"):
        uiautomator.click_element(text="Settings")
        time.sleep(2)
        uiautomator.press_back()
        time.sleep(1)
    
    for _ in range(3):
        uiautomator.swipe_down()
        time.sleep(0.5)


def main():
    tool = JankTestTool()
    
    try:
        tool.connect_device()
        print(f"Connected to device: {tool.device_id}")
        
        device_info = tool.get_device_info()
        print("\nDevice Information:")
        print(f"Devices: {device_info.get('devices', [])}")
        print(f"Battery Level: {device_info.get('battery_level', 'N/A')}%")
        
        target_package = "com.example.app"
        
        print(f"\nPreparing test environment for {target_package}...")
        tool.prepare_test_environment(target_package, clear_data=False)
        
        print("\n=== Running Test 1: Scroll Test ===")
        result1 = tool.run_test_with_trace(
            test_script=scroll_test,
            package_name=target_package,
            trace_duration=30,
            frame_threshold_ms=16.67,
            output_dir="./results",
            test_name="scroll_test"
        )
        
        print("\n=== Running Test 2: Navigation Test ===")
        result2 = tool.run_test_with_trace(
            test_script=app_navigation_test,
            package_name=target_package,
            trace_duration=20,
            frame_threshold_ms=16.67,
            output_dir="./results",
            test_name="navigation_test"
        )
        
        print("\n=== Running Test 3: Complex UI Test ===")
        result3 = tool.run_test_with_trace(
            test_script=complex_ui_test,
            package_name=target_package,
            trace_duration=25,
            frame_threshold_ms=16.67,
            output_dir="./results",
            test_name="complex_ui_test"
        )
        
        print("\n=== All tests completed! ===")
        
        test_cases = [
            {
                "name": "batch_scroll",
                "package_name": target_package,
                "test_script": scroll_test,
                "duration": 30,
                "threshold": 16.67
            },
            {
                "name": "batch_navigation",
                "package_name": target_package,
                "test_script": app_navigation_test,
                "duration": 20,
                "threshold": 16.67
            }
        ]
        
        print("\n=== Running Batch Test ===")
        batch_results = tool.batch_test(test_cases, output_dir="./batch_results")
        
        print("\nTest reports saved to ./results and ./batch_results")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()