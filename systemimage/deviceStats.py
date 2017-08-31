# Author Marius Gripsgard <mariogrip@ubports.com>

import hashlib, os, subprocess, random, string

# Get the device serial number
def getSerial():
    return subprocess.check_output(["getprop", "ro.serialno"])

# Hash the serial number
def hashSerial(serial):
    md5 = hashlib.md5()
    print(getSerial())
    md5.update(getSerial())
    return md5.hexdigest()

# retrun hashed the serial number
def getHashedSerial():
    return hashSerial(getSerial())

# Only return the first half of the hash, this way it's impossible to reverse
def splitHash(sHash):
    first = sHash[:len(sHash)//2]
    return first

def getHashedAndSplitedSerial():
    return splitHash(getHashedSerial())


class DeviceStats(object):
    """docstring for DeviceStats."""
    def __init__(self):
        self.sessionId = None
        self.instanceId = None
        self.createSessionIdIfNull()
        self.createInstanceIdIfNull()

    def createSessionIdIfNull(self):
        if not self.sessionId:
            self.sessionId = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))

    def createInstanceIdIfNull(self):
        if not self.instanceId:
            self.instanceId = getHashedAndSplitedSerial()

    # Session id is generated on each boot
    def getSessionId(self):
        self.createSessionIdIfNull()
        return self.sessionId

    # instance id is generated on first boot
    def getInstanceId(self):
        self.createInstanceIdIfNull()
        return self.instanceId
