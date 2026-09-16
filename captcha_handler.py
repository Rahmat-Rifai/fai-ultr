import sys
import requests
import time
from datetime import datetime

class CaptchaHandler:
    def __init__(self, token, max_captcha_attempts=1):
        self.token = token
        self.max_captcha_attempts = max_captcha_attempts
        self.captcha_count = 0
        self.is_captcha_triggered = False
        
        self.captcha_keywords = [
            'captcha',
            'captcha_key',
            'captcha_sitekey',
            'captcha_service',
            'captcha_rqdata',
            'human verification',
            'verify you are human',
            'prove you are human',
            'verify you\'re human',
            'prove you\'re human',
            'verify i\'m human',
            'prove i\'m human',
            'require_verification',
            'verification_required',
            'verification needed',
            'requires verification',
            'needs verification',
            'complete verification',
            'additional verification',
            'security check',
            'suspicious activity',
            'unusual activity',
            'verificación',
            'verificare',
            'überprüfung',
            'vérification',
            'solve this puzzle',
            'select all images',
            'click the squares',
            'i am human',
            'not a robot',
            'verify your identity',
            'security verification',
            'bot detection',
            'suspicious behavior',
            'automation detected',
            'select all images with',
            'click all squares containing',
            'security checkpoint'
        ]
        
        self.captcha_json_fields = [
            'captcha',
            'captcha_key',
            'captcha_sitekey',
            'captcha_service',
            'captcha_rqdata',
            'require_verification',
            'verification_required',
            'human_verification',
            'verify_human',
        ]
    
    def detect_captcha(self, response):
        if response.status_code in [400, 401, 403, 429]:
            try:
                response_data = response.json()
                if isinstance(response_data, dict):
                    response_text = str(response_data).lower()
                    
                    for keyword in self.captcha_keywords:
                        if keyword in response_text:
                            return True
                    
                    errors = response_data.get('errors', {})
                    for field, error_list in errors.items():
                        if any('captcha' in str(err).lower() for err in error_list):
                            return True
                        
                        for err in error_list:
                            err_str = str(err).lower()
                            for keyword in self.captcha_keywords:
                                if keyword in err_str:
                                    return True
                    
                    for field in self.captcha_json_fields:
                        if field in response_data:
                            return True
            except:
                pass
        
        response_text = response.text.lower()
        for keyword in self.captcha_keywords:
            if keyword in response_text:
                return True
                
        return False
    
    def handle_captcha_response(self, response):
        if self.detect_captcha(response):
            self.captcha_count += 1
            self.is_captcha_triggered = True
            
            print(f"\n{'-'*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] CAPTCHA DETECTED!")
            print(f"{'-'*60}")
            
            try:
                response_data = response.json()
                print(f"Status Code: {response.status_code}")
                print(f"Response Data: {response_data}")
            except:
                print(f"Status Code: {response.status_code}")
                print(f"Response Text: {response.text[:300]}...")
            
            print(f"\nCAPTCHA ACTION REQUIRED SOLVE MANUALLY")
            print(f"{'-'*60}\n")
            
            self.log_captcha_incident(response)
            
            self.stop_script()
            return True
            
        return False
    
    def log_captcha_incident(self, response):
        try:
            with open("captcha_log.txt", "a") as f:
                f.write(f"{'-'*60}\n")
                f.write(f"CAPTCHA DETECTED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Token: {self.token[:15]}...\n")
                f.write(f"Status Code: {response.status_code}\n")
                f.write(f"Response: {response.text[:500]}\n")
                f.write(f"Captcha Count: {self.captcha_count}/{self.max_captcha_attempts}\n")
                f.write(f"{'-'*60}\n\n")
        except:
            pass
    
    def stop_script(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Stopping script due to captcha...")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Total captcha incidents: {self.captcha_count}")
        
        with open("rpg_cycles.log", "a") as f:
            f.write(f"\nSCRIPT STOPPED DUE TO CAPTCHA at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total captcha incidents: {self.captcha_count}\n")
        
        time.sleep(3)
        sys.exit(1)
    
    def reset_captcha_count(self):
        self.captcha_count = 0
        self.is_captcha_triggered = False
    
    def get_captcha_status(self):
        return {
            'captcha_count': self.captcha_count,
            'max_attempts': self.max_captcha_attempts,
            'is_triggered': self.is_captcha_triggered,
            'remaining_attempts': self.max_captcha_attempts - self.captcha_count
        }