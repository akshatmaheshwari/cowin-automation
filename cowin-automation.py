import requests
import json
from hashlib import sha256
import sys
from urllib.parse import urlencode
import os
import time
import datetime
from configparser import ConfigParser
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from tkinter import Tk, Canvas
from PIL import Image, ImageTk

SECRET="U2FsdGVkX19+975ta/vFeS7IfQNhMGz11/qpFJlFcilVXYQ2ekG0rH9uMFIIUl3de81X8/6QkMcUUvqTJ7dzVg=="
USERAGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
AUTH_HEADERS={ "User-Agent": str(USERAGENT), "origin": "https://selfregistration.cowin.gov.in", "referer": "https://selfregistration.cowin.gov.in/" }
HEADERS={ "User-Agent": str(USERAGENT), "Authorization": "" }
SESSION_TIMEOUT=15*60
MOBILE_DIGITS=10
OTP_DIGITS=6
PINCODE_DIGITS=6
DATE_FORMAT="%d-%m-%Y"
VACCINES=[ "ANY", "COVISHIELD", "COVAXIN", "SPUTNIK V" ]
VACCINE_MIN_GAP=[ 0, 12*7, 4*7, 3*7 ]

COWIN_BASE_URL="https://cdn-api.co-vin.in/api"
GENERATE_OTP_PATH="/v2/auth/generateMobileOTP"
VALIDATE_OTP_PATH="/v2/auth/validateMobileOtp"
STATES_PATH="/v2/admin/location/states"
DISTRICTS_PATH="/v2/admin/location/districts/{}"
BENEFICIARIES_PATH="/v2/appointment/beneficiaries"
FIND_BY_DISTRICT_PATH="/v2/appointment/sessions/calendarByDistrict"
FIND_BY_PIN_PATH="/v2/appointment/sessions/calendarByPin"
CAPTCHA_PATH="/v2/auth/getRecaptcha"
SCHEDULE_PATH="/v2/appointment/schedule"

CAPTCHA_SVG="captcha.svg"
CAPTCHA_PNG="captcha.png"

MOBILE=0
ALL_BENEFICIARIES=False
VACCINE=None
BOOKING_DATE=None
CENTER_BY_PIN=False
CENTER_BY_DISTRICT=False
PINCODE=0
STATE=None
DISTRICT=None
AUTO_RETRY=False

token=""
last_auth_time=0

def print_req(req):
	print('{}\n{}\r\n{}\r\n\r\n{}'.format(
		'-----------START-----------',
		req.method + ' ' + req.url,
		'\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
		req.body,
	))

def readConfig(filename):
	global MOBILE, ALL_BENEFICIARIES, VACCINE, BOOKING_DATE, CENTER_BY_PIN, CENTER_BY_DISTRICT, PINCODE, STATE, DISTRICT, AUTO_RETRY

	try:
		config = ConfigParser(inline_comment_prefixes=('#'))
		config.read(filename)
		if ("config" not in config.sections()):
			raise ValueError("No [config] section")
		default_config = config["config"]
		if ("mobile" in default_config and default_config["mobile"] != ""):
			MOBILE = int(default_config["mobile"])
		if ("all_beneficiaries" in default_config):
			if (default_config["all_beneficiaries"].lower() == "yes"):
				ALL_BENEFICIARIES = True
			elif (default_config["all_beneficiaries"].lower() == "no"):
				ALL_BENEFICIARIES = False
		if ("vaccine" in default_config and default_config["vaccine"] != ""):
			VACCINE = VACCINES.index(default_config["vaccine"].upper())
		if ("date" in default_config and default_config["date"] != ""):
			if (default_config["date"] == "today"):
				BOOKING_DATE = datetime.date.today()
			elif (default_config["date"] == "tomorrow"):
				BOOKING_DATE = datetime.date.today() + datetime.timedelta(days=1)
			else:
				BOOKING_DATE = datetime.datetime.strptime(default_config["date"], DATE_FORMAT)
		if ("center_type" in default_config and default_config["center_type"] != ""):
			if (default_config["center_type"].lower() == "pincode"):
				CENTER_BY_PIN = True
			if (default_config["center_type"].lower() == "district"):
				CENTER_BY_DISTRICT = True
		if CENTER_BY_PIN:
			if ("pincode" in default_config and default_config["pincode"] != ""):
				PINCODE = int(default_config["pincode"])
		elif CENTER_BY_DISTRICT:
			if ("state" in default_config and default_config["state"] != ""):
				STATE = default_config["state"].lower()
			if ("district" in default_config and default_config["district"] != ""):
				DISTRICT = default_config["district"].lower()
		if ("auto_retry" in default_config and default_config["auto_retry"].lower() == "yes"):
			AUTO_RETRY = True
	except Exception as error:
		raise ValueError("Error in reading default config! - " + str(error))

def loadDefaultConfig(args):
	if (len(args) != 2):
		return
	readConfig(args[1])

def generateOtp(mobile):
	print("Generating OTP...")
	otp_data = { "mobile": str(mobile), "secret": SECRET }
	otp_post = requests.post(COWIN_BASE_URL+GENERATE_OTP_PATH, data=json.dumps(otp_data), headers=AUTH_HEADERS)
	if (otp_post.status_code != 200):
		raise ValueError("Failed to generate OTP! code={}".format(otp_post.status_code))
	otp_resp = json.loads(otp_post.text)
	return otp_resp

def validateOtp(txnId):
	otp = 0
	while (otp == 0 or len(str(otp)) != OTP_DIGITS):
		otp = int(input("Enter OTP: ") or 0)
	otp_hash = sha256(str(otp).encode()).hexdigest()
	otp_data = { "otp": str(otp_hash), "txnId": str(txnId) }
	otp_post = requests.post(COWIN_BASE_URL+VALIDATE_OTP_PATH, data=json.dumps(otp_data), headers=AUTH_HEADERS)
	if (otp_post.status_code != 200):
		raise ValueError("Failed to validate OTP! code={}".format(otp_post.status_code))
	return otp_post.status_code, json.loads(otp_post.text)

def authenticate():
	global last_auth_time, token

	last_auth_time = 0
	mobile = MOBILE
	while (mobile == 0 or len(str(mobile)) != MOBILE_DIGITS):
		mobile = int(input("Enter mobile number: "))
	while True:
		try:
			otp_resp = generateOtp(mobile)
			otp_txnid = otp_resp["txnId"]
			# TODO: otp timeout
			otp_resp_code, otp_resp = validateOtp(otp_txnid)
			break
		except ValueError as error:
			print(error)
	
	token = otp_resp["token"]
	print("Bearer: {}".format(token))
	last_auth_time = time.time()

def getBeneficiaries():
	beneficiaries_get = requests.get(COWIN_BASE_URL+BENEFICIARIES_PATH, headers=HEADERS)
	if (beneficiaries_get.status_code != 200):
		raise ValueError("Failed to get beneficiaries! code={}".format(beneficiaries_get.status_code))
	return json.loads(beneficiaries_get.text)

def getReqdBeneficiaries(beneficiaries):
	pend_bnfs = []
	print("List of beneficiaries:")
	i = 0
	for bnf in beneficiaries:
		if (bnf["vaccination_status"] == "Vaccinated"):
			print("[-] {} (Fully vaccinated)".format(bnf["name"]))
		else:
			pend_bnfs.append(bnf)
			if (bnf["vaccination_status"] == "Partially Vaccinated"):
				print("[{}] {} (Partially vaccinated)".format(i + 1, bnf["name"]))
			else:
				print("[{}] {} (Not vaccinated)".format(i + 1, bnf["name"]))
			i += 1
	if (len(pend_bnfs) == 0):
		raise ValueError("No beneficiaries pending")
	if (ALL_BENEFICIARIES):
		bnf_reqd_list_inp = ""
	else:
		bnf_reqd_list_inp = input("Enter beneficiary(s) (comma separated) [all]: ")
	bnf_reqd = []
	if (bnf_reqd_list_inp == ""):
		bnf_reqd.extend(pend_bnfs)
	else:
		bnf_reqd_nums = [int(b.strip()) for b in bnf_reqd_list_inp.split(',')]
		if (len(bnf_reqd_nums) == 0):
			raise ValueError("Invalid beneficiary(s)!")
		for num in bnf_reqd_nums:
			bnf_reqd.append(pend_bnfs[num - 1])
	return bnf_reqd

def validateBeneficiaries(chosenBeneficiaries):
	partialV = notV = 0
	vaccines = set()
	dates = set()
	for bnf in chosenBeneficiaries:
		if (bnf["vaccination_status"] == "Partially Vaccinated"):
			partialV += 1
		elif (bnf["vaccination_status"] == "Not Vaccinated"):
			notV += 1
	if ((partialV ^ notV) == 0):
		raise ValueError("Incompatible beneficiaries!")
	if (notV):
		return 1, -1, datetime.datetime.now().strftime(DATE_FORMAT)
	for bnf in chosenBeneficiaries:
		vaccines.add(bnf["vaccine"])
		dates.add(bnf["dose1_date"])
	if (len(vaccines) != 1):
		raise ValueError("Incompatible beneficiary vaccines!")
	if (len(dates) != 1):
		raise ValueError("Incompatible beneficiary dates!")
	vaccine = list(vaccines)[0]
	date = datetime.datetime.strptime(list(dates)[0], DATE_FORMAT)
	actualDate = date + datetime.timedelta(days=VACCINE_MIN_GAP[VACCINES.index(vaccine.upper())])
	return 2, VACCINES.index(vaccine.upper()), actualDate.strftime(DATE_FORMAT)

def getVaccine():
	vac = VACCINE
	while (vac not in range(len(VACCINES))):
		vac = int(input("Choose vaccine [1] Covishield [2] Covaxin [3] Sputniv V [any]: ") or 0)
	return vac

def getDate(defaultDate):
	if (BOOKING_DATE != None):
		return BOOKING_DATE.strftime(DATE_FORMAT)
	while True:
		try:
			date = datetime.datetime.strptime(input("Enter date (DD-MM-YYYY) [{}]: ".format(defaultDate)) or defaultDate, DATE_FORMAT)
			break
		except ValueError:
			continue
	return date.strftime(DATE_FORMAT)

def getCentersByPIN(date, vaccine):
	pincode = PINCODE
	while (pincode == 0 or len(str(pincode)) != PINCODE_DIGITS):
		pincode = int(input("Enter PIN: ") or 0)
	pincode_params = { "pincode": pincode, "date": date }
	if (vaccine != 0):
		pincode_params["vaccine"] = VACCINES[vaccine]
	pincode_get = requests.get(COWIN_BASE_URL+FIND_BY_PIN_PATH+"?"+urlencode(pincode_params), headers=HEADERS)
	return json.loads(pincode_get.text)

def getCentersByDistrict(date, vaccine):
	states_get = requests.get(COWIN_BASE_URL+STATES_PATH, headers=HEADERS)
	states_resp = json.loads(states_get.text)
	print("States:")
	i = 0
	state_inp = 0
	for state in states_resp["states"]:
		print("[{}] {}".format(i + 1, state["state_name"]))
		if (STATE != None and STATE == state["state_name"].lower()):
			state_inp = i + 1
		i += 1
	if (state_inp == 0):
		state_inp = int(input("Choose state [1]: ") or 1)
		if (state_inp > len(states_resp["states"])):
			raise ValueError("Invalid state")
	stateid = states_resp["states"][state_inp - 1]["state_id"]

	districts_get = requests.get(COWIN_BASE_URL+DISTRICTS_PATH.format(stateid), headers=HEADERS)
	districts_resp = json.loads(districts_get.text)
	print("Districts:")
	i = 0
	district_inp = 0
	for district in districts_resp["districts"]:
		print("[{}] {}".format(i + 1, district["district_name"]))
		if (DISTRICT != None and DISTRICT == district["district_name"].lower()):
			district_inp = i + 1
		i += 1
	if (district_inp == 0):
		district_inp = int(input("Choose district [1]: ") or 1)
		if (district_inp > len(districts_resp["districts"])):
			raise ValueError("Invalid district")
	districtid = districts_resp["districts"][district_inp - 1]["district_id"]

	district_params = { "district_id": districtid, "date": date }
	if (vaccine != 0):
		district_params["vaccine"] = VACCINES[vaccine]
	district_get = requests.get(COWIN_BASE_URL+FIND_BY_DISTRICT_PATH+"?"+urlencode(district_params), headers=HEADERS)
	return json.loads(district_get.text)

def getSession(dose, numReqdBeneficiaries, centers):
	available_sessions = []
	for center in centers[:]:
		for session in center["sessions"][:]:
			if ((dose == 1 and session["available_capacity_dose1"] >= numReqdBeneficiaries) or
				(dose == 2 and session["available_capacity_dose2"] >= numReqdBeneficiaries)):
				pass
			else:
				center["sessions"].remove(session)
		if (len(center["sessions"]) == 0):
			centers.remove(center)
		else:
			available_sessions.extend(center["sessions"])
	if (len(centers) == 0):
		raise ValueError("No available sessions!")
	print("Available sessions:")
	i = 0
	for center in centers:
		print("{}, {}, {}, {}, {} - {}".format(center["name"], center["address"], center["block_name"], center["district_name"], center["state_name"], center["pincode"]))
		for session in center["sessions"]:
			print("  [{}] {}: {} {} available for {}+".format(i + 1, session["date"], session["available_capacity"], session["vaccine"], session["min_age_limit"]))
			i += 1
	sess_num = int(input("Choose session [1]: ") or 1)
	sess_chosen = available_sessions[sess_num - 1]
	if (len(sess_chosen["slots"]) == 0):
		raise ValueError("No available slots!")
	print("Available slots:")
	i = 0
	for slot in sess_chosen["slots"]:
		print("[{}] {}".format(i + 1, slot))
		i += 1
	slot_num = int(input("Choose slot [1]: ") or 1)
	sessid = sess_chosen["session_id"]
	slot = sess_chosen["slots"][slot_num - 1]
	return sessid, slot

class Captcha:
	def __enter__(self):
		devnull = open(os.devnull, "w")
		self.oldstdout_fno = os.dup(sys.stdout.fileno())
		self.oldstderr_fno = os.dup(sys.stderr.fileno())
		os.dup2(devnull.fileno(), sys.stdout.fileno())
		os.dup2(devnull.fileno(), sys.stderr.fileno())
		return self

	def __init__(self):
		pass

	def draw(self):
		# TODO: add timestamp to captcha files to support parallel runs
		if os.environ.get('DISPLAY','') == '':
			os.environ.__setitem__('DISPLAY', ':0.0')
		drawing = svg2rlg(CAPTCHA_SVG)
		try:
			renderPM.drawToFile(drawing, CAPTCHA_PNG, fmt="PNG")
		except (renderPM.RenderPMError, OSError) as error:
			return
		root = Tk()
		root.title("Captcha")
		img = Image.open(CAPTCHA_PNG)
		pimg = ImageTk.PhotoImage(img)
		size = img.size
		frame = Canvas(root, width=size[0], height=size[1])
		frame.pack()
		frame.create_image(0, 0, anchor='nw', image=pimg)
		root.geometry("{}x{}".format(size[0] + 100, size[1]))
		root.mainloop()

	def __exit__(self, type, value, traceback):
		os.dup2(self.oldstdout_fno, sys.stdout.fileno())
		os.dup2(self.oldstderr_fno, sys.stderr.fileno())

def getCaptcha():
	captcha_post = requests.post(COWIN_BASE_URL+CAPTCHA_PATH, headers=HEADERS)
	if (captcha_post.status_code != 200):
		raise ValueError("Failed to get captcha! code={}".format(captcha_post.status_code))
	captcha_resp = json.loads(captcha_post.text)
	captcha_svg = captcha_resp["captcha"]
	f = open(CAPTCHA_SVG, "w")
	f.write(captcha_svg)
	f.close()
	print("Generating captcha...")
	with Captcha() as cap:
		cap.draw()
	captcha = input("Enter captcha (see {} or {}): ".format(CAPTCHA_SVG, CAPTCHA_PNG))
	if (os.path.exists(CAPTCHA_SVG)):
		os.remove(CAPTCHA_SVG)
	if (os.path.exists(CAPTCHA_PNG)):
		os.remove(CAPTCHA_PNG)
	return captcha

def scheduleAppointment(schedule_data):
	schedule_post = requests.post(COWIN_BASE_URL+SCHEDULE_PATH, data=json.dumps(schedule_data), headers=HEADERS)
	return schedule_post.status_code, json.loads(schedule_post.text)

def main():
	global HEADERS

	loadDefaultConfig(sys.argv)

	first_run = True
	while True:
		try:
			if (time.time() - last_auth_time >= SESSION_TIMEOUT):
				# TODO: alarm for expired session
				authenticate()
			HEADERS["Authorization"] = "Bearer {}".format(token)

			if (first_run or (not AUTO_RETRY)):
				beneficiaries_resp = getBeneficiaries()
				bnf_reqd = getReqdBeneficiaries(beneficiaries_resp["beneficiaries"])
				dose, vaccine, date = validateBeneficiaries(bnf_reqd)
				bnfid_list = [bnf["beneficiary_reference_id"] for bnf in bnf_reqd]
				if (vaccine == -1):	# else decided based on first dose
					vaccine = getVaccine()
				date = getDate(date)
				searchType = 1 if CENTER_BY_PIN else 2 if CENTER_BY_DISTRICT else 0
				while (searchType not in [1, 2]):
					searchType = int(input("Search by [1] PIN [2] District: ") or 0)
				if (searchType == 1):
					center_resp = getCentersByPIN(date, vaccine)
				else:
					center_resp = getCentersByDistrict(date, vaccine)
				first_run = False
			else:
				time.sleep(4)

			sessid, slot = getSession(dose, len(bnf_reqd), center_resp["centers"])
			# TODO: print pre-booking summary
			captcha = getCaptcha()
			schedule_data = { "dose": dose, "session_id": sessid, "slot": slot, "beneficiaries": [bnfid_list], "captcha": captcha }
			schedule_respcode, schedule_resp = scheduleAppointment(schedule_data)
			if (schedule_respcode == 200):
				sys.exit("Success! {}".format(schedule_respcode))
			else:
				print("{} Failure! {} ({})".format(schedule_respcode, schedule_resp["error"], schedule_resp["errorCode"]))

		except (ValueError, ConnectionError) as error:
			print(error)
		time.sleep(1)

if __name__ == "__main__":
	try:
		main()
	except Exception as error:
		print(error)
		input("Press enter to exit")
	except KeyboardInterrupt:
		sys.exit("\nQuit!!")
