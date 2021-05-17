import requests
import json
import hashlib
import sys
import urllib
# from svglib.svglib import svg2rlg
# from reportlab.graphics import renderPM
import os
import time
import datetime

DEFAULT_MOBILE=9811208262
SECRET="U2FsdGVkX19+975ta/vFeS7IfQNhMGz11/qpFJlFcilVXYQ2ekG0rH9uMFIIUl3de81X8/6QkMcUUvqTJ7dzVg=="
USERAGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
SESSION_TIMEOUT=15*60
OTP_DIGITS=6
DATE_FORMAT="%d-%m-%Y"
MIN_DAYS_COVISHIELD = 12*7
MIN_DAYS_COVAXIN = 4*7

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
# CAPTCHA_PNG="captcha.png"

token=""
last_auth_time=0

def print_req(req):
	print('{}\n{}\r\n{}\r\n\r\n{}'.format(
		'-----------START-----------',
		req.method + ' ' + req.url,
		'\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
		req.body,
	))

def generateOtp(mobile):
	headers = { "User-Agent": str(USERAGENT) }

	print("Generating OTP...")
	otp_data = { "mobile": str(mobile), "secret": SECRET }
	otp_post = requests.post(COWIN_BASE_URL+GENERATE_OTP_PATH, data=json.dumps(otp_data), headers=headers)
	if (otp_post.status_code != 200):
		raise ValueError("Failed to generate OTP! code={}".format(otp_post.status_code))
	otp_resp = json.loads(otp_post.text)
	return otp_resp

def validateOtp(txnId):
	headers = { "User-Agent": str(USERAGENT) }

	otp = 0
	while (otp == 0 or len(str(otp)) != OTP_DIGITS):
		otp = int(input("Enter OTP: ") or 0)
	otp_hash = hashlib.sha256(str(otp).encode()).hexdigest()
	otp_data = { "otp": str(otp_hash), "txnId": str(txnId) }
	otp_post = requests.post(COWIN_BASE_URL+VALIDATE_OTP_PATH, data=json.dumps(otp_data), headers=headers)
	if (otp_post.status_code != 200):
		raise ValueError("Failed to validate OTP! code={}".format(otp_post.status_code))
	return otp_post.status_code, json.loads(otp_post.text)

def authenticate():
	global last_auth_time
	global token

	last_auth_time = 0
	mobile = int(input("Enter mobile number [{}]: ".format(str(DEFAULT_MOBILE))) or DEFAULT_MOBILE)
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
	print("Bearer: " + token)
	last_auth_time = time.time()

def getBeneficiaries():
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	beneficiaries_get = requests.get(COWIN_BASE_URL+BENEFICIARIES_PATH, headers=headers)
	if (beneficiaries_get.status_code != 200):
		raise ValueError("Failed to get beneficiaries! code={}".format(beneficiaries_get.status_code))
	return json.loads(beneficiaries_get.text)

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
		return 1, "", time.strftime(DATE_FORMAT, time.localtime())
	for bnf in chosenBeneficiaries:
		vaccines.add(bnf["vaccine"])
		dates.add(bnf["dose1_date"])
	if (len(vaccines) != 1):
		raise ValueError("Incompatible beneficiary vaccines!")
	if (len(dates) != 1):
		raise ValueError("Incompatible beneficiary dates!")
	vaccine = list(vaccines)[0]
	date = datetime.datetime.strptime(list(dates)[0], DATE_FORMAT)
	if (vaccine == "COVISHIELD"):
		actualDate = date + datetime.timedelta(days=MIN_DAYS_COVISHIELD)
	elif (vaccine == "COVAXIN"):
		actualDate = date + datetime.timedelta(days=MIN_DAYS_COVAXIN)
	return 2, vaccine, actualDate.strftime(DATE_FORMAT)

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
	dose, vaccine, date = validateBeneficiaries(bnf_reqd)
	return bnf_reqd, dose, vaccine, date

def getVaccine():
	vaccine_mapping = { 0: "", 1: "COVISHIELD", 2: "COVAXIN" }
	vac = -1
	while (vac not in vaccine_mapping.keys()):
		vac = int(input("Choose vaccine [1] Covishield [2] Covaxin [any]: ") or 0)
	return vaccine_mapping[vac]

def getDate(defaultDate):
	while True:
		try:
			date = time.strptime(input("Enter date (DD-MM-YYYY) [{}]: ".format(defaultDate)) or defaultDate, DATE_FORMAT)
			break
		except ValueError:
			continue
	return time.strftime(DATE_FORMAT, date)

def getCentersByPIN(date, vaccine):
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	pincode = int(input("Enter PIN: "))
	pincode_params = { "pincode": pincode, "date": date, "vaccine": vaccine }
	pincode_get = requests.get(COWIN_BASE_URL+FIND_BY_PIN_PATH+"?"+urllib.parse.urlencode(pincode_params), headers=headers)
	return json.loads(pincode_get.text)

def getCentersByDistrict(date, vaccine):
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	states_get = requests.get(COWIN_BASE_URL+STATES_PATH, headers=headers)
	states_resp = json.loads(states_get.text)
	print("States:")
	i = 0
	for state in states_resp["states"]:
		print("[{}] {}".format(i + 1, state["state_name"]))
		i += 1
	state_inp = int(input("Choose state [1]: ") or 1)
	if (state_inp > len(states_resp["states"])):
		raise ValueError("Invalid state")
	stateid = states_resp["states"][state_inp - 1]["state_id"]

	districts_get = requests.get(COWIN_BASE_URL+DISTRICTS_PATH.format(stateid), headers=headers)
	districts_resp = json.loads(districts_get.text)
	print("Districts:")
	i = 0
	for district in districts_resp["districts"]:
		print("[{}] {}".format(i + 1, district["district_name"]))
		i += 1
	district_inp = int(input("Choose district [1]: ") or 1)
	if (district_inp > len(districts_resp["districts"])):
		raise ValueError("Invalid district")
	districtid = districts_resp["districts"][district_inp - 1]["district_id"]

	district_params = { "district_id": districtid, "date": date, "vaccine": vaccine }
	district_get = requests.get(COWIN_BASE_URL+FIND_BY_DISTRICT_PATH+"?"+urllib.parse.urlencode(district_params), headers=headers)
	return json.loads(district_get.text)

def getSession(dose, numReqdBeneficiaries, centers):
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	available_sessions = []
	for center in centers[:]:
		for session in center["sessions"][:]:
			if ((dose == 1 and session["available_capacity_dose1"] >= numReqdBeneficiaries) or
				(dose == 2 and session["available_capacity_dose2"] >= numReqdBeneficiaries)):
				x = 1
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

def getCaptcha():
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	captcha_post = requests.post(COWIN_BASE_URL+CAPTCHA_PATH, headers=headers)
	if (captcha_post.status_code != 200):
		raise ValueError("Failed to get captcha! code={}".format(captcha_post.status_code))
	captcha_resp = json.loads(captcha_post.text)
	captcha_svg = captcha_resp["captcha"]
	f = open(CAPTCHA_SVG, "w")
	f.write(captcha_svg)
	f.close()
	# drawing = svg2rlg(CAPTCHA_SVG)
	# renderPM.drawToFile(drawing, CAPTCHA_PNG, fmt="PNG")
	captcha = input("Enter captcha (see {}): ".format(CAPTCHA_SVG))
	os.remove(CAPTCHA_SVG)
	return captcha

def scheduleAppointment(schedule_data):
	headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

	schedule_post = requests.post(COWIN_BASE_URL+SCHEDULE_PATH, data=json.dumps(schedule_data), headers=headers)
	return schedule_post.status_code, json.loads(schedule_post.text)

def main():
	while True:
		try:
			if (time.time() - last_auth_time >= SESSION_TIMEOUT):
				# TODO: alarm for expired session
				authenticate()

			headers = { "User-Agent": str(USERAGENT), "authorization": "Bearer {}".format(token) }

			beneficiaries_resp = getBeneficiaries()

			bnf_reqd, dose, vaccine, date = getReqdBeneficiaries(beneficiaries_resp["beneficiaries"])
			bnfid_list = [bnf["beneficiary_reference_id"] for bnf in bnf_reqd]

			if (vaccine == ""):
				vaccine = getVaccine()

			date = getDate(date)

			searchType = 0
			while (searchType not in [1, 2]):
				searchType = int(input("Search by [1] PIN [2] District: ") or 0)
			if (searchType == 1):
				center_resp = getCentersByPIN(date, vaccine)
			else:
				center_resp = getCentersByDistrict(date, vaccine)

			sessid, slot = getSession(dose, len(bnf_reqd), center_resp["centers"])

			captcha = getCaptcha()

			schedule_data = { "dose": dose, "session_id": sessid, "slot": slot, "beneficiaries": [bnfid_list], "captcha": captcha }
			schedule_respcode, schedule_resp = scheduleAppointment(schedule_data)
			if (schedule_respcode == 200):
				print("Success!", schedule_respcode)
			else:
				print("{} Failure! {} ({})".format(schedule_respcode, schedule_resp["error"], schedule_resp["errorCode"]))

		except (ValueError, ConnectionError) as error:
			print(error)
		time.sleep(1)

if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		sys.exit("\nQuit!!")
