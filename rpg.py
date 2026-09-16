import time
from datetime import datetime

import automation_state

RPG_TASKS = [
    ("lh", 0.1),
    ("lb", 0.1),
    ("lucy", 15),
 
]

def execute_rpg_cycle(cycle_number, send_message_func, handle_neonutil_sequence_func):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] CYCLE #{cycle_number}: Starting")
    
    for command, delay in RPG_TASKS:
        # Stop sending new commands as soon as the automation is stopped.
        if not automation_state.bot_running:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] AUTOMATION STOPPED — aborting cycle")
            return False

        if command == "[NEONUTIL_MONITOR]":
            handle_neonutil_sequence_func()
            if delay > 0:
                time.sleep(delay)
        else:
            if not send_message_func(command, 0):
                # No point retrying once the automation has been stopped.
                if not automation_state.bot_running:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] AUTOMATION STOPPED — aborting cycle")
                    return False
                time.sleep(2)
                if not send_message_func(command, 0):
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: Failed to send")
            if delay > 0:
                time.sleep(delay)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] CYCLE #{cycle_number}: Completed")
    
    with open("rpg_cycles.log", "a") as f:
        f.write(f"Cycle #{cycle_number} completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return True
