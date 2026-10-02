// Route the Mac's sound to your speakers or headphones AND to BlackHole, and put it back after.
//
//   audio_route start   create "Fieldnotes Output" (current output + BlackHole), make it the
//                       default output, print the previous output's UID
//   audio_route stop UID  restore that output and remove "Fieldnotes Output"
//
// Uses CoreAudio's aggregate-device API with `stacked` set: a multi-output device, the same thing
// Audio MIDI Setup creates by hand.
import CoreAudio
import Foundation

let deviceName = "Fieldnotes Output"
let deviceUID = "fieldnotes.multi-output"
let blackHoleName = "BlackHole 2ch"

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
}

func allDevices() -> [AudioDeviceID] {
    var addr = address(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    return ids
}

func string(_ id: AudioDeviceID, _ selector: AudioObjectPropertySelector) -> String {
    var addr = address(selector)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &value) == noErr,
        let value
    else { return "" }
    return value.takeRetainedValue() as String
}

func defaultOutput() -> AudioDeviceID {
    var addr = address(kAudioHardwarePropertyDefaultOutputDevice)
    var id = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &id)
    return id
}

func setDefaultOutput(_ id: AudioDeviceID) {
    for selector in [kAudioHardwarePropertyDefaultOutputDevice,
                     kAudioHardwarePropertyDefaultSystemOutputDevice] {
        var addr = address(selector)
        var value = id
        let status = AudioObjectSetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil,
            UInt32(MemoryLayout<AudioDeviceID>.size), &value)
        if status != noErr { fail("Could not set the default output (error \(status))") }
    }
}

func device(uid: String) -> AudioDeviceID? {
    allDevices().first { string($0, kAudioDevicePropertyDeviceUID) == uid }
}

func device(named name: String) -> AudioDeviceID? {
    allDevices().first { string($0, kAudioObjectPropertyName) == name }
}

func removeOurDevice() {
    if let id = device(uid: deviceUID) { AudioHardwareDestroyAggregateDevice(id) }
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "" {
case "start":
    removeOurDevice()  // left over from a run that did not end cleanly
    let current = defaultOutput()
    let currentUID = string(current, kAudioDevicePropertyDeviceUID)
    guard let blackHole = device(named: blackHoleName) else {
        fail("\(blackHoleName) not found. Run ./install.sh.")
    }
    if current == blackHole { fail("The Mac's output is BlackHole itself: pick your speakers first.") }
    let description: [String: Any] = [
        kAudioAggregateDeviceNameKey: deviceName,
        kAudioAggregateDeviceUIDKey: deviceUID,
        kAudioAggregateDeviceIsStackedKey: 1,  // multi-output: every sub-device plays everything
        kAudioAggregateDeviceIsPrivateKey: 0,  // public, so it can be the system output
        kAudioAggregateDeviceMainSubDeviceKey: currentUID,  // your speakers keep the clock
        kAudioAggregateDeviceSubDeviceListKey: [
            [kAudioSubDeviceUIDKey: currentUID],
            [kAudioSubDeviceUIDKey: string(blackHole, kAudioDevicePropertyDeviceUID),
             kAudioSubDeviceDriftCompensationKey: 1],
        ],
    ]
    var created = AudioDeviceID(0)
    let status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &created)
    if status != noErr { fail("Could not create \(deviceName) (error \(status))") }
    Thread.sleep(forTimeInterval: 0.3)  // CoreAudio publishes the new device asynchronously
    setDefaultOutput(created)
    print(currentUID)
case "stop":
    guard args.count > 2 else { fail("usage: audio_route stop PREVIOUS_UID") }
    if let previous = device(uid: args[2]) { setDefaultOutput(previous) }
    removeOurDevice()
case "name":
    print(string(defaultOutput(), kAudioObjectPropertyName))
default:
    fail("usage: audio_route start | stop PREVIOUS_UID | name")
}
