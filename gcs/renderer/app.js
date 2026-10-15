'use strict'

// ── helpers ───────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id)
const DEG = Math.PI / 180
const R2D = 180 / Math.PI
function clamp (v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
function fmt1 (v) { return (typeof v === 'number' ? v.toFixed(1) : '—') }
function fmt2 (v) { return (typeof v === 'number' ? v.toFixed(2) : '—') }
function fmt6 (v) { return (typeof v === 'number' ? v.toFixed(6) : '—') }
function now ()   { return new Date().toLocaleTimeString('en-GB', {hour12:false}) }

// ── shared state ──────────────────────────────────────────────────────────────
const S = {
  speed: 0, vspeed: 0, altitude: 0, heading: 0,
  roll: 0, pitch: 0, yaw: 0,
  vx: 0, vy: 0, vz: 0,
  battery: { pct: 0, voltage: 0 },
  motors: [0, 0, 0, 0, 0, 0],
  armed: false, mode: '—',
  gps: { lat: null, lon: null, altAbs: null, fix: 0, sats: 0 },
  trail: [],
  barcodes: [],
  detections: [],
  dbLog: [],
  volumetry: [],
  lidar: null,
  occMap: null,
  slamPose: { x: 0, y: 0, theta: 0 },
  slamTrail: [],
  loopClosures: 0,
  altHistory: [], spdHistory: [], vspdHistory: [],
  flightStart: null,
  activeView: 'dashboard',
  // brain / mission planner
  plannedPath:  [],
  wpIndex:      0,
  missionName:  '—',
  missionDone:  false,
  coordOrigin:  null,   // {lat, lon, slamX, slamY} — GPS↔SLAM alignment snapshot
  // pi services (controlled from dashboard)
  svcStatus: { slam: 'stopped', camera: 'stopped', camera2: 'stopped', mjpeg: 'stopped', mavros: 'stopped', brain: 'stopped', barcode: 'stopped' },
}

const HIST_MAX = 120   // 120 data points per chart

// ── tab switching ─────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'))
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'))
    btn.classList.add('active')
    $('view-' + btn.dataset.view).classList.add('active')
    S.activeView = btn.dataset.view
    resizeCanvases()
  })
})

// ── ROS connection ────────────────────────────────────────────────────────────
let ROS_URL = localStorage.getItem('ros_url') || 'ws://raspi5.local:9090'
let ros = null, reconnTimer = null

function setDot (state) {
  $('ros-dot').className = state
}

function connect () {
  if (ros) { try { ros.close() } catch (_) {} }
  setDot('connecting')
  $('ros-url').textContent = ROS_URL.replace(/^wss?:\/\//, '')
  ros = new ROSLIB.Ros({ url: ROS_URL })
  ros.on('connection', () => { setDot('connected'); clearTimeout(reconnTimer); subscribe() })
  ros.on('error',      () => { setDot('error');     sched() })
  ros.on('close',      () => { setDot('error');     sched() })

  // Attempt MJPEG camera on same host, port 8080
  const host = ROS_URL.replace(/^wss?:\/\//, '').replace(/:\d+$/, '')
  connectMJPEG(`http://${host}:8080/cam1`)
}

// ── MJPEG camera ──────────────────────────────────────────────────────────────
function connectMJPEG (url) {
  const img    = $('cam1-img')
  const canvas = $('cam1')
  const sig    = $('cam1-sig')

  img.onload = () => {
    // First frame loaded — switch to img, hide test pattern canvas
    img.style.display   = 'block'
    canvas.style.display = 'none'
    sig.textContent  = 'LIVE'
    sig.className    = 'cam-sig ok'
  }

  img.onerror = () => {
    img.style.display    = 'none'
    canvas.style.display = 'block'
    sig.textContent  = 'NO SIGNAL'
    sig.className    = 'cam-sig no'
    // Retry after 3 s
    setTimeout(() => { if (img.src) img.src = url + '?t=' + Date.now() }, 3000)
  }

  img.src = url
}
function sched () { clearTimeout(reconnTimer); reconnTimer = setTimeout(connect, 3000) }

// ── network discovery ─────────────────────────────────────────────────────────

// Try to open a WebSocket and resolve true if it connects within `ms`
function probeWS (url, ms) {
  return new Promise(resolve => {
    let done = false
    const finish = ok => { if (!done) { done = true; resolve(ok) } }
    const t = setTimeout(() => { try { ws.close() } catch (_) {} finish(false) }, ms)
    let ws
    try {
      ws = new WebSocket(url)
      ws.onopen  = () => { clearTimeout(t); try { ws.close() } catch (_) {} finish(true)  }
      ws.onerror = () => { clearTimeout(t); finish(false) }
    } catch (_) { clearTimeout(t); finish(false) }
  })
}

// Get local IP via WebRTC ICE candidate (works in Electron / Chromium)
function getLocalIP () {
  return new Promise(resolve => {
    const pc = new RTCPeerConnection({ iceServers: [] })
    pc.createDataChannel('')
    pc.createOffer().then(o => pc.setLocalDescription(o)).catch(() => resolve(null))
    const t = setTimeout(() => { pc.close(); resolve(null) }, 1500)
    pc.onicecandidate = ({ candidate }) => {
      if (!candidate) return
      const m = /([0-9]{1,3}(?:\.[0-9]{1,3}){3})/.exec(candidate.candidate)
      if (m && !m[1].startsWith('127.')) {
        clearTimeout(t); pc.close(); resolve(m[1])
      }
    }
  })
}

// Scan a /24 subnet for open rosbridge port 9090.
// onFound(ip) called for each live host; returns when scan completes.
async function scanSubnet (subnet, port, onFound, onProgress) {
  const BATCH = 40   // parallel probes at a time
  const TOUT  = 400  // ms per probe
  let scanned = 0
  for (let start = 1; start <= 254; start += BATCH) {
    const tasks = []
    for (let i = start; i <= Math.min(start + BATCH - 1, 254); i++) {
      const ip = `${subnet}.${i}`
      tasks.push(
        probeWS(`ws://${ip}:${port}`, TOUT).then(ok => {
          scanned++
          onProgress(scanned)
          if (ok) onFound(ip)
        })
      )
    }
    await Promise.all(tasks)
  }
}

// ── connection popover ────────────────────────────────────────────────────────
function initConnPopover () {
  const pop   = $('conn-popover')
  const input = $('ros-input')
  const urlEl = $('ros-url')

  urlEl.addEventListener('click', e => {
    e.stopPropagation()
    const open = pop.style.display === 'block'
    pop.style.display = open ? 'none' : 'block'
    if (!open) { input.value = ROS_URL; input.focus(); input.select() }
  })

  $('btn-connect').addEventListener('click', () => {
    let url = input.value.trim()
    if (!url) return
    if (!/^wss?:\/\//.test(url)) url = 'ws://' + url
    ROS_URL = url
    localStorage.setItem('ros_url', ROS_URL)
    pop.style.display = 'none'
    clearTimeout(reconnTimer)
    connect()
  })

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  $('btn-connect').click()
    if (e.key === 'Escape') pop.style.display = 'none'
  })

  document.addEventListener('click', e => {
    if (!pop.contains(e.target) && e.target !== urlEl) pop.style.display = 'none'
  })

  // ── network scan ───────────────────────────────────────────────────────────
  const scanBtn     = $('scan-btn')
  const scanStatus  = $('scan-status')
  const scanResults = $('scan-results')

  function addScanHost (label, url, tag) {
    const div = document.createElement('div')
    div.className = 'scan-host'
    div.innerHTML =
      `<div class="sh-info">
         <span class="sh-ip">${label}</span>
         ${tag ? `<span class="sh-tag">${tag}</span>` : ''}
       </div>
       <button class="sh-use">Use</button>`
    div.querySelector('.sh-use').addEventListener('click', () => {
      input.value = url
      $('btn-connect').click()
    })
    scanResults.appendChild(div)
  }

  scanBtn.addEventListener('click', async () => {
    scanBtn.disabled = true
    scanResults.innerHTML = ''
    scanStatus.textContent = 'Trying raspberrypi.local…'

    let found = 0

    // 1 — mDNS shortcut (works if Avahi is running on the Pi)
    const mdnsUrl = 'ws://raspberrypi.local:9090'
    if (await probeWS(mdnsUrl, 1200)) {
      found++
      addScanHost('raspberrypi.local', mdnsUrl, '● Raspberry Pi (mDNS)')
      scanStatus.textContent = `Found via mDNS — scanning subnet too…`
    }

    // 2 — subnet scan
    const localIP = await getLocalIP()
    if (!localIP) {
      scanStatus.textContent = found
        ? `Found ${found} host(s). Could not detect subnet.`
        : 'Could not detect local IP. Enter URL manually.'
      scanBtn.disabled = false
      return
    }

    const subnet = localIP.split('.').slice(0, 3).join('.')
    scanStatus.textContent = `Scanning ${subnet}.0/24…`

    await scanSubnet(subnet, 9090,
      ip => { found++; addScanHost(ip, `ws://${ip}:9090`, '') },
      n  => { scanStatus.textContent = `Scanning ${subnet}.0/24… (${n}/254)` }
    )

    scanStatus.textContent = found
      ? `Found ${found} host(s) with port 9090 open.`
      : `No hosts found on ${subnet}.0/24 with port 9090 open.`
    scanBtn.disabled = false
  })
}
function sub (name, type, cb) {
  const t = new ROSLIB.Topic({ ros, name, messageType: type })
  t.subscribe(cb)
  return t
}

// ── ROS service / publish helpers ─────────────────────────────────────────────
function rosService (name, type, req, cb) {
  if (!ros) return
  const svc = new ROSLIB.Service({ ros, name, serviceType: type })
  svc.callService(new ROSLIB.ServiceRequest(req), cb || (() => {}))
}

function rosPub (name, type, msg) {
  if (!ros) return
  const t = new ROSLIB.Topic({ ros, name, messageType: type })
  t.publish(new ROSLIB.Message(msg))
}

// ── command log ───────────────────────────────────────────────────────────────
function addCmdLog (cmd, result) {
  const lastEl = $('cmd-last')
  if (lastEl) {
    lastEl.textContent = cmd
    lastEl.style.color = result === 'FAIL' ? 'var(--danger)'
                       : result === 'SENT' ? 'var(--accent)' : 'var(--ok)'
  }
  const log = $('cmd-log')
  if (!log) return
  const cls = result === 'OK' ? 'clok' : result === 'FAIL' ? 'clfail'
            : result === 'SENT' ? 'clsent' : 'clwarn'
  const row = document.createElement('div')
  row.className = 'cmd-log-row'
  row.innerHTML = `<span class="clt">${now()}</span><span class="${cls}">${cmd} → ${result}</span>`
  log.prepend(row)
  while (log.children.length > 25) log.removeChild(log.lastChild)
}

// ── drone commands (via mavlink_bridge /drone/cmd topic) ─────────────────────
let _droneCmdPub  = null
let _armPendingTs = 0

function droneCmd (payload) {
  if (!ros) return
  if (!_droneCmdPub) {
    _droneCmdPub = new ROSLIB.Topic({ ros, name: '/drone/cmd', messageType: 'std_msgs/String' })
  }
  _droneCmdPub.publish(new ROSLIB.Message({ data: JSON.stringify(payload) }))
}

function cmdArm () {
  const t = Date.now()
  if (t - _armPendingTs < 800) {
    _armPendingTs = 0
    droneCmd({ action: 'arm' })
    addCmdLog('ARM', 'SENT')
  } else {
    _armPendingTs = t
    addCmdLog('ARM', 'click again to confirm')
  }
}

function cmdDisarm () {
  droneCmd({ action: 'disarm' })
  addCmdLog('DISARM', 'SENT')
}

function cmdSetMode (mode) {
  droneCmd({ action: 'mode', mode })
  addCmdLog('MODE ' + mode, 'SENT')
}

function cmdTakeoff () {
  const alt = parseFloat($('tkoff-alt').value) || 5
  droneCmd({ action: 'takeoff', alt })
  addCmdLog('TAKEOFF ' + alt + 'm', 'SENT')
}

function cmdLand () {
  droneCmd({ action: 'land' })
  addCmdLog('LAND', 'SENT')
}

function cmdGoto () {
  const x = parseFloat($('sp-x').value) || 0
  const y = parseFloat($('sp-y').value) || 0
  const z = parseFloat($('sp-z').value) || 5
  droneCmd({ action: 'goto', x, y, z })
  addCmdLog(`GOTO x=${x} y=${y} z=${z}`, 'SENT')
}

function cmdVelStop () {
  droneCmd({ action: 'vel_stop' })
  addCmdLog('VEL STOP', 'SENT')
}

// ── SLAM commands ─────────────────────────────────────────────────────────────
function slamSaveMap () {
  rosService('/slam_toolbox/save_map', 'slam_toolbox/SaveMap',
    { name: { data: 'gcs_map_' + Date.now() } },
    r => addCmdLog('SAVE MAP', r && r.result === 0 ? 'OK' : 'FAIL'))
}

function slamToggle (enable) {
  rosService('/slam_toolbox/toggle_interactive_mode', 'slam_toolbox/ToggleInteractive',
    {},
    () => addCmdLog(enable ? 'SLAM START' : 'SLAM PAUSE', 'SENT'))
}

function slamResetPose () {
  rosService('/slam_toolbox/clear_changes', 'slam_toolbox/ClearChanges', {},
    () => addCmdLog('SLAM RESET', 'SENT'))
}

// ── init controls ─────────────────────────────────────────────────────────────
function initControls () {
  $('btn-arm').addEventListener('click', cmdArm)
  $('btn-disarm').addEventListener('click', cmdDisarm)
  $('btn-takeoff').addEventListener('click', cmdTakeoff)
  $('btn-land').addEventListener('click', cmdLand)
  $('btn-rtl').addEventListener('click', () => cmdSetMode('RTL'))

  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'))
      btn.classList.add('active')
      cmdSetMode(btn.dataset.mode)
    })
  })

  $('btn-goto').addEventListener('click', cmdGoto)
  $('btn-vel-stop').addEventListener('click', cmdVelStop)
  $('btn-hold').addEventListener('click', () => cmdSetMode('LOITER'))

  $('btn-slam-start').addEventListener('click', () => slamToggle(true))
  $('btn-slam-pause').addEventListener('click', () => slamToggle(false))
  $('btn-slam-save').addEventListener('click', slamSaveMap)
  $('btn-slam-reset').addEventListener('click', slamResetPose)
  $('btn-slam-clear').addEventListener('click', () => {
    SLAM3D.clearMap()
    $('sl-pts').textContent = '0'
    addCmdLog('Map cleared', 'ok')
  })
}

// ── subscriptions ─────────────────────────────────────────────────────────────
function subscribe () {
  // speed + heading + altitude  (mavlink_bridge → /drone/vfr JSON)
  sub('/drone/vfr', 'std_msgs/String', m => {
    try {
      const d   = JSON.parse(m.data)
      S.speed   = d.airspeed  ?? d.groundspeed ?? 0
      S.vspeed  = d.climb     ?? 0
      S.heading = d.heading   ?? 0
      S.altitude = d.alt      ?? 0
      pushHist(S.spdHistory,  S.speed)
      pushHist(S.vspdHistory, S.vspeed)
      pushHist(S.altHistory,  S.altitude)
    } catch (_) {}
  })

  // battery
  sub('/mavros/battery', 'sensor_msgs/BatteryState', m => {
    const raw = m.percentage ?? 0
    S.battery.pct     = raw > 1 ? raw : raw * 100
    S.battery.voltage = m.voltage ?? 0
  })

  // attitude (quaternion → euler)
  sub('/mavros/imu/data', 'sensor_msgs/Imu', m => {
    const q = m.orientation
    S.roll  = Math.atan2(2*(q.w*q.x + q.y*q.z), 1 - 2*(q.x*q.x + q.y*q.y)) * R2D
    S.pitch = Math.asin (clamp(2*(q.w*q.y - q.z*q.x), -1, 1)) * R2D
    S.yaw   = Math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z)) * R2D
  })

  // velocity body frame
  sub('/mavros/local_position/velocity_body', 'geometry_msgs/TwistStamped', m => {
    S.vx = m.twist.linear.x ?? 0
    S.vy = m.twist.linear.y ?? 0
    S.vz = m.twist.linear.z ?? 0
  })

  // GPS
  sub('/mavros/global_position/global', 'sensor_msgs/NavSatFix', m => {
    S.gps.lat    = m.latitude
    S.gps.lon    = m.longitude
    S.gps.altAbs = m.altitude
    // Capture GPS↔SLAM alignment origin once we have both
    if (!S.coordOrigin && (S.slamPose.x !== 0 || S.slamPose.y !== 0)) {
      S.coordOrigin = { lat: m.latitude, lon: m.longitude, slamX: S.slamPose.x, slamY: S.slamPose.y }
    }
    if (S.trail.length === 0 ||
        Math.abs(S.trail[S.trail.length-1].lat - m.latitude)  > 1e-7 ||
        Math.abs(S.trail[S.trail.length-1].lon - m.longitude) > 1e-7) {
      S.trail.push({ lat: m.latitude, lon: m.longitude })
      if (S.trail.length > 500) S.trail.shift()
    }
  })

  // GPS status  (mavlink_bridge → /drone/gps_status JSON)
  sub('/drone/gps_status', 'std_msgs/String', m => {
    try {
      const d    = JSON.parse(m.data)
      S.gps.fix  = d.fix_type           ?? 0
      S.gps.sats = d.satellites_visible ?? 0
    } catch (_) {}
  })

  // state — armed / mode  (mavlink_bridge → /drone/state JSON)
  sub('/drone/state', 'std_msgs/String', m => {
    try {
      const d = JSON.parse(m.data)
      if (d.armed && !S.armed) S.flightStart = Date.now()
      if (!d.armed) S.flightStart = null
      S.armed = d.armed ?? false
      S.mode  = d.mode  || '—'
    } catch (_) {}
  })

  // motor throttle  (mavlink_bridge → /drone/motors JSON {channels:[pwm…]})
  sub('/drone/motors', 'std_msgs/String', m => {
    try {
      const ch = JSON.parse(m.data).channels || []
      for (let i = 0; i < 6; i++) {
        const pwm = ch[i] ?? 1000
        S.motors[i] = clamp((pwm - 1000) / 1000 * 100, 0, 100)
      }
    } catch (_) {}
  })

  // Point-LIO — nube de puntos registrada (frame camera_init)
  sub('/cloud_registered', 'sensor_msgs/PointCloud2', m => {
    const xyz = decodePC2xyz(m)
    SLAM3D.addScan(xyz)
    $('sl-pts').textContent   = SLAM3D.count.toLocaleString()
    $('sl-astep').textContent = '3D'
    $('sl-status').textContent = 'Active'
    $('sl-status').className   = 'sv ok'
  })

  // Point-LIO — odometría (/Odometry si existe, fallback por TF)
  sub('/Odometry', 'nav_msgs/Odometry', m => {
    const p = m.pose.pose
    S.slamPose.x = p.position.x
    S.slamPose.y = p.position.y
    const q = p.orientation
    S.slamPose.theta = Math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z)) * R2D
    updateSlamPoseUI()
    pushSlamTrail()
  })

  // Point-LIO pose via /tf topic — subscribe directly, no tf2_web_republisher needed
  sub('/tf', 'tf2_msgs/TFMessage', m => {
    const tr = (m.transforms || []).find(t =>
      t.header.frame_id === 'camera_init' && t.child_frame_id === 'aft_mapped')
    if (!tr) return
    const p = tr.transform.translation
    S.slamPose.x = p.x
    S.slamPose.y = p.y
    const q = tr.transform.rotation
    S.slamPose.theta = Math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z)) * R2D
    updateSlamPoseUI()
    pushSlamTrail()
  })

  // GCS control node — service status
  sub('/gcs/status', 'std_msgs/String', m => {
    try { S.svcStatus = JSON.parse(m.data) } catch (_) {}
    updateSvcUI()
  })

  // Brain node — planned path
  sub('/brain/planned_path', 'std_msgs/String', m => {
    try {
      const d       = JSON.parse(m.data)
      S.plannedPath = d.waypoints   || []
      S.wpIndex     = d.wp_index    ?? 0
      S.missionName = d.mission     || '—'
      S.missionDone = d.done        || false
    } catch (_) {}
  })

  // Barcode detection — carries SLAM location from barcode_detector.py
  sub('/barcode/detection', 'std_msgs/String', m => {
    let code = m.data, status = 'OK', x = null, y = null, theta = null
    try {
      const j = JSON.parse(m.data)
      code   = j.barcode || j.code || m.data
      status = j.status  || 'OK'
      x      = j.slam_x     ?? null
      y      = j.slam_y     ?? null
      theta  = j.slam_theta ?? null
    } catch (_) {}
    // Fall back to live SLAM pose if detector didn't embed it
    const entry = {
      code, status, time: now(),
      x:     x     ?? (S.slamPose.x !== 0 ? S.slamPose.x : null),
      y:     y     ?? (S.slamPose.y !== 0 ? S.slamPose.y : null),
      theta: theta ?? S.slamPose.theta,
    }
    S.barcodes.unshift(entry)
    if (S.barcodes.length > 200) S.barcodes.pop()
    S.detections.unshift({ label: 'Barcode', id: code, conf: '100%', time: entry.time })
    if (S.detections.length > 100) S.detections.pop()
    addDbLog(code, status)
    updateDbTable()
    updateDetectTable()
  })

  // Volumetry (std_msgs/String carrying JSON: {length,width,height,volume,confidence,object_id})
  sub('/detection/volume', 'std_msgs/String', m => {
    let vol = {}
    try { vol = JSON.parse(m.data) } catch (_) { return }
    const entry = {
      length: vol.length     ?? 0,
      width:  vol.width      ?? 0,
      height: vol.height     ?? 0,
      volume: vol.volume     ?? (vol.length * vol.width * vol.height) ?? 0,
      conf:   vol.confidence ?? vol.conf ?? 0,
      id:     vol.object_id  ?? vol.id   ?? '—',
      time:   now(),
    }
    S.volumetry.unshift(entry)
    if (S.volumetry.length > 50) S.volumetry.pop()
    updateVolumetryPanel()
    S.detections.unshift({ label: 'Volume', id: entry.id, conf: Math.round(entry.conf * 100) + '%', time: entry.time })
    if (S.detections.length > 100) S.detections.pop()
    updateDetectTable()
  })

  // Compressed camera frames
  // cam1  — dashboard: raw forward feed
  subCamImage('/camera/forward/image_raw/compressed', 'cam1',  'cam1-sig', 180, [0, 2])
  // icam1 — image processing tab: ROI-annotated feed from barcode_detector.py
  subCamImage('/barcode/roi/image/compressed', 'icam1', 'icam1-sig', 0, null)
}

// Subscribe to a compressed image topic and draw to a canvas by id
// rotation: 0 | 90 | 180 | 270 (degrees clockwise)
// swap: null | [a, b] — swap pixel channels a and b (0=R,1=G,2=B) e.g. [0,1] fixes R↔G
function subCamImage (topic, canvasId, sigId, rotation = 0, swap = null) {
  if (!canvasId) return
  sub(topic, 'sensor_msgs/CompressedImage', m => {
    const canvas = $(canvasId)
    if (!canvas) return
    try {
      const raw = atob(m.data)
      const buf = new Uint8Array(raw.length)
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
      createImageBitmap(new Blob([buf], { type: 'image/jpeg' })).then(bitmap => {
        const W = canvas.width, H = canvas.height
        const ctx = canvas.getContext('2d')
        ctx.save()
        if (rotation === 180) {
          ctx.translate(W, H); ctx.rotate(Math.PI)
          ctx.drawImage(bitmap, 0, 0, W, H)
        } else if (rotation === 90) {
          ctx.translate(W, 0); ctx.rotate(Math.PI / 2)
          ctx.drawImage(bitmap, 0, 0, H, W)
        } else if (rotation === 270) {
          ctx.translate(0, H); ctx.rotate(-Math.PI / 2)
          ctx.drawImage(bitmap, 0, 0, H, W)
        } else {
          ctx.drawImage(bitmap, 0, 0, W, H)
        }
        ctx.restore()
        if (swap) {
          const [a, b] = swap
          const id = ctx.getImageData(0, 0, W, H), d = id.data
          for (let i = 0; i < d.length; i += 4) {
            const t = d[i+a]; d[i+a] = d[i+b]; d[i+b] = t
          }
          ctx.putImageData(id, 0, 0)
        }
        bitmap.close()
        if (sigId) { const s = $(sigId); if (s) { s.textContent = 'LIVE'; s.className = 'cam-sig ok' } }
      }).catch(() => {})
    } catch (_) {}
  })
}

// ── history helper ────────────────────────────────────────────────────────────
function pushHist (arr, v) {
  arr.push(v)
  if (arr.length > HIST_MAX) arr.shift()
}

function pushSlamTrail () {
  const { x, y } = S.slamPose
  const last = S.slamTrail[S.slamTrail.length - 1]
  if (!last || Math.abs(last.x - x) > 0.1 || Math.abs(last.y - y) > 0.1) {
    S.slamTrail.push({ x, y })
    if (S.slamTrail.length > 2000) S.slamTrail.shift()
  }
}

// ── Services panel ────────────────────────────────────────────────────────────
// "camera" UI button controls both 'camera' and 'mjpeg' services on the Pi
const SVC_UI = ['slam', 'camera', 'mavros', 'brain', 'barcode']

function updateSvcUI () {
  SVC_UI.forEach(svc => {
    const dot = $('svc-dot-' + svc)
    const btn = $('svc-btn-' + svc)
    if (!dot || !btn) return
    // CAMERA button reflects camera + camera2 + mjpeg
    const isRunning = svc === 'camera'
      ? ['camera','camera2','mjpeg'].some(k => S.svcStatus[k] === 'running')
      : S.svcStatus[svc] === 'running'
    dot.className = 'svc-dot' + (isRunning ? ' running' : '')
    btn.textContent = isRunning ? 'Stop' : 'Start'
    btn.className   = 'svc-btn' + (isRunning ? ' running' : '')
  })
}

let _svcPub = null
function toggleService (svc) {
  if (!ros || ros.isConnected === false) return
  if (!_svcPub) {
    _svcPub = new ROSLIB.Topic({ ros, name: '/gcs/cmd', messageType: 'std_msgs/String' })
  }
  // CAMERA button controls forward cam, downward cam, and MJPEG server together
  const group = svc === 'camera' ? ['camera', 'camera2', 'mjpeg'] : [svc]
  const isRunning = group.some(k => S.svcStatus[k] === 'running')
  const action = isRunning ? 'stop' : 'start'

  // Barcode needs camera running — auto-start camera services when starting barcode
  if (svc === 'barcode' && action === 'start') {
    ;['camera', 'camera2', 'mjpeg'].forEach(s => {
      if (S.svcStatus[s] !== 'running') {
        _svcPub.publish(new ROSLIB.Message({ data: JSON.stringify({ action: 'start', service: s }) }))
      }
    })
  }

  group.forEach(s => {
    _svcPub.publish(new ROSLIB.Message({ data: JSON.stringify({ action, service: s }) }))
  })
}

// ── DOM updates (text/badges) ─────────────────────────────────────────────────
function updateDOM () {
  // header badges
  const armEl = $('hdr-armed')
  armEl.textContent = S.armed ? 'ARMED' : 'DISARMED'
  armEl.className   = 'hdr-badge' + (S.armed ? ' armed' : '')
  $('hdr-mode').textContent = S.mode
  $('hdr-mode').className   = 'hdr-badge active'

  const fixTxt = S.gps.fix >= 3 ? '3D FIX' : S.gps.fix >= 2 ? '2D FIX' : 'NO GPS'
  const gpsEl  = $('hdr-gps')
  gpsEl.textContent = fixTxt
  gpsEl.className   = 'hdr-badge' + (S.gps.fix >= 3 ? ' ok' : '')

  // dashboard KPIs
  $('val-bat').textContent     = S.battery.pct > 0 ? Math.round(S.battery.pct) : '—'
  $('val-volt').textContent    = S.battery.voltage > 0 ? fmt2(S.battery.voltage) + ' V' : '— V'
  $('val-lat').textContent     = fmt6(S.gps.lat)
  $('val-lon').textContent     = fmt6(S.gps.lon)
  $('val-alt-abs').textContent = fmt1(S.gps.altAbs)
  $('val-sats').textContent    = S.gps.sats || '—'

  const pillArm  = $('pill-arm')
  pillArm.textContent = S.armed ? 'ARMED' : 'DISARMED'
  pillArm.className   = 'pill' + (S.armed ? ' armed' : '')
  const pillMode = $('pill-mode')
  pillMode.textContent = S.mode
  pillMode.className   = 'pill active'

  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === S.mode)
  })

  // brain mission status badge
  const brainEl = $('brain-status')
  if (brainEl) {
    if (S.missionDone) {
      brainEl.textContent = 'Mission complete'
      brainEl.style.color = 'var(--ok)'
    } else if (S.plannedPath.length > 0) {
      const wp = S.plannedPath[S.wpIndex]
      const lbl = wp ? (wp.label || `wp-${S.wpIndex}`) : '—'
      brainEl.textContent = `WP ${S.wpIndex + 1}/${S.plannedPath.length}: ${lbl}`
      brainEl.style.color = 'var(--warn)'
    } else {
      brainEl.textContent = 'No mission'
      brainEl.style.color = 'var(--muted)'
    }
  }

  // navigation view
  $('nav-spd').textContent   = fmt1(S.speed)   + ' m/s'
  $('nav-vspd').textContent  = fmt1(S.vspeed)  + ' m/s'
  $('nav-alt').textContent   = fmt1(S.altitude) + ' m'
  $('nav-hdg').textContent   = Math.round(S.heading) + '°'
  $('nav-roll').textContent  = fmt1(S.roll)  + '°'
  $('nav-pitch').textContent = fmt1(S.pitch) + '°'
  $('nav-yaw').textContent   = fmt1(S.yaw)   + '°'
  $('nav-vx').textContent    = fmt2(S.vx) + ' m/s'
  $('nav-vy').textContent    = fmt2(S.vy) + ' m/s'
  $('nav-vz').textContent    = fmt2(S.vz) + ' m/s'
  $('nav-sats').textContent  = S.gps.sats || '—'
  $('nav-fix').textContent   = fixTxt
  $('nav-lat').textContent   = fmt6(S.gps.lat)
  $('nav-lon').textContent   = fmt6(S.gps.lon)
  $('nav-armed').textContent = S.armed ? 'ARMED' : 'DISARMED'
  $('nav-mode').textContent  = S.mode

  // flight timer
  if (S.flightStart) {
    const s = Math.floor((Date.now() - S.flightStart) / 1000)
    const mm = String(Math.floor(s/60)).padStart(2,'0')
    const ss = String(s % 60).padStart(2,'0')
    $('nav-ftime').textContent = mm + ':' + ss
  } else {
    $('nav-ftime').textContent = '00:00'
  }
}

function updateDbTable () {
  const countEl = $('db-count')
  if (countEl) countEl.textContent = S.barcodes.length + ' record' + (S.barcodes.length !== 1 ? 's' : '')
  const last = S.barcodes[0]
  if (last) {
    const el = $('db-last-code')
    if (el) {
      el.textContent = last.code
      el.className   = 'bc-badge bc-new'
      setTimeout(() => el.classList.remove('bc-new'), 900)
    }
  }
  const tbody = $('db-tbody')
  if (!tbody) return
  tbody.innerHTML = ''
  S.barcodes.slice(0, 20).forEach(r => {
    const tr = document.createElement('tr')
    tr.innerHTML = `<td style="font-family:monospace">${r.code}</td><td style="color:var(--muted)">${r.time}</td><td class="db-ok">${r.status}</td>`
    tbody.appendChild(tr)
  })
}

function updateDetectTable () {
  const countEl = $('db-count')
  if (countEl) countEl.textContent = S.barcodes.length

  const tbody = $('detect-tbody')
  if (!tbody) return
  tbody.innerHTML = ''
  S.barcodes.slice(0, 100).forEach(r => {
    const tr  = document.createElement('tr')
    const pos = (r.x != null && r.y != null)
      ? `${r.x.toFixed(2)}, ${r.y.toFixed(2)}`
      : '—'
    tr.innerHTML =
      `<td style="color:var(--muted);font-family:monospace;font-size:10px">${r.time}</td>` +
      `<td style="font-family:monospace;font-weight:700;color:var(--ok)">${r.code}</td>` +
      `<td style="color:var(--text)">${r.code}</td>` +
      `<td style="color:var(--accent);font-family:monospace;font-size:10px">${pos}</td>`
    tbody.appendChild(tr)
  })
}

function exportBarcodeCSV () {
  const rows = [['Hora', 'Codi', 'Producte', 'Posicio X (m)', 'Posicio Y (m)', 'Estat']]
  S.barcodes.forEach(r => {
    rows.push([
      r.time,
      r.code,
      r.code,
      r.x != null ? r.x.toFixed(3) : '',
      r.y != null ? r.y.toFixed(3) : '',
      r.status,
    ])
  })
  const csv  = rows.map(r =>
    r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')
  ).join('\r\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `inventari_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function addDbLog (code, status) {
  const list = $('db-log-list')
  const cls  = status === 'OK' ? 'log-ok' : 'log-warn'
  const div  = document.createElement('div')
  div.className = 'log-entry'
  div.innerHTML = `<span class="log-time">${now()}</span><span class="log-msg ${cls}">DB INSERT → ${code} [${status}]</span>`
  list.prepend(div)
  while (list.children.length > 60) list.removeChild(list.lastChild)
}

function updateVolumetryPanel () {
  const last = S.volumetry[0]
  if (!last) return
  $('vol-val').textContent   = last.volume.toFixed(4)
  $('vol-l').textContent     = last.length.toFixed(3) + ' m'
  $('vol-w').textContent     = last.width.toFixed(3)  + ' m'
  $('vol-h').textContent     = last.height.toFixed(3) + ' m'
  $('vol-count').textContent = S.volumetry.length
  $('vol-conf').textContent  = Math.round(last.conf * 100) + '%'

  const list = $('vol-log-list')
  list.innerHTML = ''
  S.volumetry.slice(0, 25).forEach(v => {
    const div = document.createElement('div')
    div.className = 'vol-entry'
    div.innerHTML =
      `<div class="vol-dims">${v.length.toFixed(2)}&times;${v.width.toFixed(2)}&times;${v.height.toFixed(2)} m &rarr; ${v.volume.toFixed(4)} m&sup3;</div>` +
      `<div class="vol-time">${v.time} &middot; ${Math.round(v.conf * 100)}% conf &middot; ID: ${v.id}</div>`
    list.appendChild(div)
  })
}

// ── canvas drawing ────────────────────────────────────────────────────────────

function drawSpeedometer () {
  const canvas = $('gauge-speed')
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  const cx = W/2, cy = H/2
  const R  = Math.min(W,H) * 0.40
  const SA = 210 * DEG          // start angle (7 o'clock)
  const TA = 240 * DEG          // total arc
  const MAX = 20                // m/s
  const pct = clamp(S.speed / MAX, 0, 1)

  ctx.clearRect(0, 0, W, H)

  // track
  ctx.beginPath(); ctx.arc(cx, cy, R, SA, SA+TA)
  ctx.strokeStyle = '#2a2f3a'; ctx.lineWidth = 14; ctx.lineCap = 'round'; ctx.stroke()

  // coloured fill arc
  const speedColor = pct < 0.5 ? '#3ddc84' : pct < 0.75 ? '#f0a500' : '#e04040'
  if (pct > 0) {
    ctx.beginPath(); ctx.arc(cx, cy, R, SA, SA + pct * TA)
    ctx.strokeStyle = speedColor; ctx.lineWidth = 14; ctx.lineCap = 'round'; ctx.stroke()
  }

  // tick marks
  for (let i = 0; i <= MAX; i += 5) {
    const a   = SA + (i/MAX)*TA
    const cos = Math.cos(a), sin = Math.sin(a)
    ctx.beginPath()
    ctx.moveTo(cx + cos*(R-10), cy + sin*(R-10))
    ctx.lineTo(cx + cos*(R+4),  cy + sin*(R+4))
    ctx.strokeStyle = '#3a4050'; ctx.lineWidth = 1.5; ctx.lineCap = 'butt'; ctx.stroke()
    ctx.fillStyle = '#5a6072'; ctx.font = '9px sans-serif'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(i, cx + Math.cos(a)*(R+15), cy + Math.sin(a)*(R+15))
  }

  // needle
  const na  = SA + pct * TA
  ctx.beginPath()
  ctx.moveTo(cx - Math.cos(na)*12, cy - Math.sin(na)*12)
  ctx.lineTo(cx + Math.cos(na)*(R-14), cy + Math.sin(na)*(R-14))
  ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2; ctx.lineCap = 'round'; ctx.stroke()
  ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI*2)
  ctx.fillStyle = speedColor; ctx.fill()

  // digital readout
  ctx.fillStyle = '#cdd3de'
  ctx.font = `bold ${Math.floor(W*0.17)}px 'Courier New',monospace`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(S.speed.toFixed(1), cx, cy + R*0.28)
  ctx.fillStyle = '#5a6072'; ctx.font = '10px sans-serif'
  ctx.fillText('m/s', cx, cy + R*0.52)
}

function drawBatteryArc () {
  const canvas = $('gauge-battery')
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  const cx = W/2, cy = H/2 + 4, R = Math.min(W,H)*0.36
  const SA = 210*DEG, TA = 240*DEG
  const pct = clamp(S.battery.pct / 100, 0, 1)
  const col = pct > 0.5 ? '#3ddc84' : pct > 0.2 ? '#f0a500' : '#e04040'

  ctx.clearRect(0,0,W,H)
  ctx.beginPath(); ctx.arc(cx,cy,R,SA,SA+TA)
  ctx.strokeStyle = '#2a2f3a'; ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.stroke()
  if (pct > 0) {
    ctx.beginPath(); ctx.arc(cx,cy,R,SA,SA+pct*TA)
    ctx.strokeStyle = col; ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.stroke()
  }
  ctx.fillStyle = col; ctx.font = 'bold 13px monospace'
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(Math.round(S.battery.pct)+'%', cx, cy)
}

function drawMotor (id, pct) {
  const canvas = $(id)
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  const cx = W/2, cy = H/2, R = Math.min(W,H)*0.38
  const SA = 225*DEG, TA = 270*DEG
  const col = pct < 60 ? '#3ddc84' : pct < 80 ? '#f0a500' : '#e04040'

  ctx.clearRect(0,0,W,H)
  ctx.beginPath(); ctx.arc(cx,cy,R,SA,SA+TA)
  ctx.strokeStyle = '#2a2f3a'; ctx.lineWidth = 9; ctx.lineCap = 'round'; ctx.stroke()
  if (pct > 0) {
    ctx.beginPath(); ctx.arc(cx,cy,R,SA,SA+(pct/100)*TA)
    ctx.strokeStyle = col; ctx.lineWidth = 9; ctx.lineCap = 'round'; ctx.stroke()
  }
  // RPM indicator dots
  const dots = 6
  for (let i = 0; i < dots; i++) {
    const a   = (i/dots)*Math.PI*2 - Math.PI/2
    const r2  = R - 14
    const lit = i < Math.round((pct/100)*dots)
    ctx.beginPath(); ctx.arc(cx+Math.cos(a)*r2, cy+Math.sin(a)*r2, 2.5, 0, Math.PI*2)
    ctx.fillStyle = lit ? col : '#2a2f3a'; ctx.fill()
  }
  ctx.fillStyle = '#cdd3de'; ctx.font = 'bold 13px monospace'
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(Math.round(pct)+'%', cx, cy)
}

function drawHexDiagram () {
  const canvas = $('hex-diagram')
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, W, H)

  const cx = W / 2, cy = H / 2
  const sz  = Math.min(W, H)
  const reach = sz * 0.36          // centre → motor knob centre (px)
  const scale = reach / 0.5        // normalised unit → px
  const mR  = sz * 0.092           // knob outer radius
  // Rotary knob sweep: 270° starting at 7:30 (canvas 225°) going clockwise
  const SA = 225 * DEG, TA = 270 * DEG

  const MOTORS = [
    { n:1, sx: 0.50, sy: 0.00, ccw:false },
    { n:2, sx:-0.50, sy: 0.00, ccw:true  },
    { n:3, sx:-0.25, sy:-0.43, ccw:false },
    { n:4, sx: 0.25, sy: 0.43, ccw:true  },
    { n:5, sx: 0.25, sy:-0.43, ccw:true  },
    { n:6, sx:-0.25, sy: 0.43, ccw:false },
  ]

  // ── 1. Arms ────────────────────────────────────────────────────────────
  ctx.lineWidth = sz * 0.008
  MOTORS.forEach(m => {
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + m.sx * scale, cy + m.sy * scale)
    ctx.strokeStyle = '#2a3040'; ctx.stroke()
  })

  // ── 2. Rotary-knob gauges ──────────────────────────────────────────────
  MOTORS.forEach(m => {
    const pct = S.motors[m.n - 1] || 0
    const t   = pct / 100
    const mx  = cx + m.sx * scale
    const my  = cy + m.sy * scale
    const idleCol = m.ccw ? '#4d9fff' : '#3ddc84'
    const thrCol  = pct < 30 ? '#3ddc84' : pct < 70 ? '#f0a500' : '#e04040'
    const activeCol = pct > 0 ? thrCol : idleCol

    // ── Arc track (full range) ──────────────────────
    ctx.lineCap = 'round'
    ctx.beginPath(); ctx.arc(mx, my, mR, SA, SA + TA)
    ctx.strokeStyle = '#1a2030'; ctx.lineWidth = mR * 0.30; ctx.stroke()

    // ── Filled arc (current thrust) ─────────────────
    if (pct > 0) {
      ctx.beginPath(); ctx.arc(mx, my, mR, SA, SA + t * TA)
      ctx.strokeStyle = thrCol; ctx.lineWidth = mR * 0.30; ctx.stroke()
    }

    // ── Knob disc (radial gradient for 3-D depth) ───
    const gx = mx - mR * 0.22, gy = my - mR * 0.22
    const grad = ctx.createRadialGradient(gx, gy, mR * 0.04, mx, my, mR * 0.70)
    grad.addColorStop(0, '#3e4558')
    grad.addColorStop(1, '#141820')
    ctx.beginPath(); ctx.arc(mx, my, mR * 0.70, 0, Math.PI * 2)
    ctx.fillStyle = grad; ctx.fill()
    ctx.strokeStyle = '#2a3040'; ctx.lineWidth = 1; ctx.stroke()

    // ── Pointer (rotates with thrust) ───────────────
    const ptrA = SA + t * TA
    ctx.beginPath()
    ctx.moveTo(mx + Math.cos(ptrA) * mR * 0.15, my + Math.sin(ptrA) * mR * 0.15)
    ctx.lineTo(mx + Math.cos(ptrA) * mR * 0.60, my + Math.sin(ptrA) * mR * 0.60)
    ctx.strokeStyle = pct > 0 ? thrCol : '#3a4050'
    ctx.lineWidth = mR * 0.14; ctx.lineCap = 'round'; ctx.stroke()

    // Pointer cap dot
    ctx.beginPath(); ctx.arc(mx, my, mR * 0.11, 0, Math.PI * 2)
    ctx.fillStyle = pct > 0 ? thrCol : '#3a4050'; ctx.fill()

    // ── CW / CCW direction ring ──────────────────────
    ctx.beginPath(); ctx.arc(mx, my, mR * 1.14, 0, Math.PI * 2)
    ctx.strokeStyle = activeCol + '55'; ctx.lineWidth = 1.5; ctx.lineCap = 'butt'; ctx.stroke()

    // ── Labels ───────────────────────────────────────
    const fs = Math.max(8, Math.round(mR * 0.38))
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillStyle = '#5a6072'
    ctx.font = `bold ${fs}px monospace`
    ctx.fillText('M' + m.n, mx, my - mR * 0.22)
    ctx.fillStyle = pct > 0 ? thrCol : '#3a4050'
    ctx.font = `bold ${Math.max(7, Math.round(mR * 0.34))}px monospace`
    ctx.fillText(Math.round(pct) + '%', mx, my + mR * 0.26)
  })

  // ── 3. Central body hub ────────────────────────────────────────────────
  const hubR = sz * 0.052
  const hubG = ctx.createRadialGradient(cx - hubR*0.3, cy - hubR*0.3, hubR*0.05, cx, cy, hubR)
  hubG.addColorStop(0, '#7a8499')
  hubG.addColorStop(1, '#3a4050')
  ctx.beginPath(); ctx.arc(cx, cy, hubR, 0, Math.PI * 2)
  ctx.fillStyle = hubG; ctx.fill()
  ctx.strokeStyle = '#8a93a8'; ctx.lineWidth = 1.5; ctx.stroke()

  // Nose direction indicator (forward triangle)
  const ns = sz * 0.022
  ctx.beginPath()
  ctx.moveTo(cx, cy - ns * 1.4)
  ctx.lineTo(cx - ns * 0.8, cy + ns * 0.6)
  ctx.lineTo(cx + ns * 0.8, cy + ns * 0.6)
  ctx.closePath(); ctx.fillStyle = '#e04040'; ctx.fill()
}

function drawMap () {
  const canvas = $('map-canvas')
  const wrap   = $('map-wrap')
  if (!canvas || !wrap) return
  const W = wrap.clientWidth, H = wrap.clientHeight - 24
  if (W < 10 || H < 10) return
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')

  ctx.fillStyle = '#0d1520'; ctx.fillRect(0, 0, W, H)

  // grid
  ctx.strokeStyle = '#162030'; ctx.lineWidth = 1
  for (let x = 0; x < W; x += 40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke() }
  for (let y = 0; y < H; y += 40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke() }

  // compass labels
  ctx.fillStyle = '#2e3a4a'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center'
  ctx.fillText('N', W/2, 12); ctx.fillText('S', W/2, H-4)
  ctx.textAlign = 'left';  ctx.fillText('W', 4, H/2+4)
  ctx.textAlign = 'right'; ctx.fillText('E', W-4, H/2+4)

  const cx = W/2, cy = H/2
  const hasGPS  = !!S.gps.lat
  const hasSLAM = S.slamTrail.length > 1 || S.slamPose.x !== 0 || S.slamPose.y !== 0
  const hasPlan = S.plannedPath.length > 0

  if (!hasGPS && !hasSLAM) {
    ctx.fillStyle = '#5a6072'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('Awaiting GPS or SLAM…', W/2, H/2); return
  }

  // ── projections ─────────────────────────────────────────────────────────
  const gpsScale = Math.min(W, H) / 2 / 0.0018   // ~200 m radius in GPS mode
  const projGPS  = (lat, lon) => ({
    x: cx + (lon - S.gps.lon) * gpsScale,
    y: cy - (lat - S.gps.lat) * gpsScale,
  })

  const slamScale = 50   // px per metre in SLAM-only mode
  const projSLAM  = (sx, sy) => ({
    x: cx + (sx - S.slamPose.x) * slamScale,
    y: cy - (sy - S.slamPose.y) * slamScale,
  })

  // Convert a SLAM local point → GPS, then → canvas (needs coordOrigin)
  // Assumes SLAM X ≈ East, Y ≈ North (ENU). Valid when drone starts facing north.
  const slamToCanvas = (sx, sy) => {
    if (hasGPS && S.coordOrigin) {
      const dx = sx - S.coordOrigin.slamX
      const dy = sy - S.coordOrigin.slamY
      const lat = S.coordOrigin.lat + dy / 111320
      const lon = S.coordOrigin.lon + dx / (111320 * Math.cos(S.coordOrigin.lat * DEG))
      return projGPS(lat, lon)
    }
    if (hasSLAM) return projSLAM(sx, sy)
    return null
  }

  // ── planned path (dashed orange) ─────────────────────────────────────────
  if (hasPlan) {
    const pts = S.plannedPath.map(wp => slamToCanvas(wp.x, wp.y)).filter(p => p)

    if (pts.length > 1) {
      ctx.save()
      ctx.setLineDash([6, 5])
      ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 1.5
      ctx.beginPath()
      pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y))
      ctx.stroke()
      ctx.restore()
    }

    // Waypoint markers
    S.plannedPath.forEach((wp, i) => {
      const p = slamToCanvas(wp.x, wp.y)
      if (!p) return
      const reached = i < S.wpIndex
      const current = i === S.wpIndex
      ctx.beginPath(); ctx.arc(p.x, p.y, current ? 6 : 4, 0, Math.PI * 2)
      ctx.fillStyle = reached ? '#3ddc84' : current ? '#f0a500' : 'rgba(240,165,0,.35)'
      ctx.fill()
      if (current) {
        ctx.beginPath(); ctx.arc(p.x, p.y, 10, 0, Math.PI * 2)
        ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 1.2; ctx.stroke()
      }
      if (wp.label) {
        ctx.fillStyle = reached ? '#3ddc84' : '#f0a500'
        ctx.font = '9px sans-serif'; ctx.textAlign = 'left'
        ctx.fillText(wp.label, p.x + 9, p.y + 3)
      }
    })
  }

  // ── real path (solid blue) ───────────────────────────────────────────────
  ctx.setLineDash([])
  if (hasGPS) {
    if (S.trail.length > 1) {
      ctx.beginPath()
      S.trail.forEach((pt, i) => {
        const p = projGPS(pt.lat, pt.lon)
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)
      })
      ctx.strokeStyle = 'rgba(77,159,255,.7)'; ctx.lineWidth = 2; ctx.stroke()
    }
    // home cross
    if (S.trail.length > 0) {
      const h = projGPS(S.trail[0].lat, S.trail[0].lon)
      ctx.strokeStyle = '#3ddc84'; ctx.lineWidth = 1.5
      ctx.beginPath(); ctx.moveTo(h.x-6,h.y); ctx.lineTo(h.x+6,h.y); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(h.x,h.y-6); ctx.lineTo(h.x,h.y+6); ctx.stroke()
    }
    // drone marker (centre = current GPS)
    ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2)
    ctx.fillStyle = '#4d9fff'; ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()
    // heading ray
    const ha = (S.heading - 90) * DEG
    ctx.beginPath(); ctx.moveTo(cx, cy)
    ctx.lineTo(cx + Math.cos(ha)*18, cy + Math.sin(ha)*18)
    ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 1.5; ctx.stroke()
  } else {
    // SLAM-only: trail in local frame centred on current pose
    if (S.slamTrail.length > 1) {
      ctx.beginPath()
      S.slamTrail.forEach((pt, i) => {
        const p = projSLAM(pt.x, pt.y)
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)
      })
      ctx.strokeStyle = 'rgba(77,159,255,.7)'; ctx.lineWidth = 2; ctx.stroke()
    }
    // drone marker at canvas centre
    ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2)
    ctx.fillStyle = '#4d9fff'; ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()
    // scale bar
    const barPx = 5 * slamScale
    const bx = W - 16, by = H - 14
    ctx.strokeStyle = '#5a6072'; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(bx-barPx,by); ctx.lineTo(bx,by); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(bx-barPx,by-3); ctx.lineTo(bx-barPx,by+3); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(bx,by-3); ctx.lineTo(bx,by+3); ctx.stroke()
    ctx.fillStyle = '#5a6072'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('5m', bx - barPx/2, by - 5)
    // pose readout
    ctx.fillStyle = '#4a5060'; ctx.font = '9px sans-serif'; ctx.textAlign = 'left'
    ctx.fillText(`x:${S.slamPose.x.toFixed(1)} y:${S.slamPose.y.toFixed(1)}`, 6, H - 6)
  }

  // ── legend (shown only when a mission is loaded) ─────────────────────────
  if (hasPlan) {
    const lx = 8, ly = H - 42
    ctx.fillStyle = 'rgba(13,21,32,.82)'
    ctx.fillRect(lx - 3, ly - 13, 118, 38)
    ctx.setLineDash([])
    ctx.strokeStyle = 'rgba(77,159,255,.7)'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(lx+18, ly); ctx.stroke()
    ctx.fillStyle = '#5a6072'; ctx.font = '9px sans-serif'; ctx.textAlign = 'left'
    ctx.fillText('real path', lx + 22, ly + 3)
    ctx.save(); ctx.setLineDash([5, 4])
    ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 1.5
    ctx.beginPath(); ctx.moveTo(lx, ly+17); ctx.lineTo(lx+18, ly+17); ctx.stroke()
    ctx.restore()
    ctx.fillStyle = '#5a6072'
    ctx.fillText('planned', lx + 22, ly + 20)
  }
}

function drawHorizon () {
  const canvas = $('horizon-canvas')
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  const cx = W/2, cy = H/2, R = Math.min(W,H)*0.44

  ctx.clearRect(0,0,W,H)

  // clip circle
  ctx.save()
  ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.clip()

  // pitch offset: 4px per degree
  const pitchOff = S.pitch * 4
  ctx.save()
  ctx.translate(cx,cy); ctx.rotate(-S.roll*DEG)

  // sky
  ctx.fillStyle = '#1a3a6a'
  ctx.fillRect(-R, -R - pitchOff, R*2, R*2)
  // ground
  ctx.fillStyle = '#4a2e0a'
  ctx.fillRect(-R, -pitchOff, R*2, R*2)
  // horizon line
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5
  ctx.beginPath(); ctx.moveTo(-R*1.2, -pitchOff); ctx.lineTo(R*1.2, -pitchOff); ctx.stroke()

  // pitch lines
  for (let p = -30; p <= 30; p += 10) {
    if (p === 0) continue
    const y = -pitchOff - p*4
    const w = p % 20 === 0 ? 40 : 24
    ctx.beginPath(); ctx.moveTo(-w,-y+pitchOff*0-p*4); ctx.lineTo(w,y-(-pitchOff)*0+p*4)
    // simplified: just horizontal marks at pitch offsets
    ctx.beginPath(); ctx.moveTo(-w, -p*4-pitchOff); ctx.lineTo(w, -p*4-pitchOff)
    ctx.strokeStyle = 'rgba(255,255,255,.4)'; ctx.lineWidth = 1; ctx.stroke()
    ctx.fillStyle = 'rgba(255,255,255,.5)'; ctx.font = '8px sans-serif'
    ctx.textAlign = 'right'; ctx.fillText(p+'°', -w-3, -p*4-pitchOff+3)
  }
  ctx.restore()
  ctx.restore()

  // outer ring
  ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2)
  ctx.strokeStyle = '#3a4050'; ctx.lineWidth = 2; ctx.stroke()

  // fixed aircraft symbol
  ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 2.5; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.moveTo(cx-30,cy); ctx.lineTo(cx-10,cy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx+10,cy); ctx.lineTo(cx+30,cy); ctx.stroke()
  ctx.beginPath(); ctx.arc(cx,cy,4,0,Math.PI*2)
  ctx.fillStyle = '#f0a500'; ctx.fill()

  // roll arc at top
  const rollR = R - 8
  const rollA = S.roll * DEG
  ctx.save(); ctx.translate(cx,cy)
  // roll tick
  ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(Math.cos(-Math.PI/2+rollA)*(rollR-8), Math.sin(-Math.PI/2+rollA)*(rollR-8))
  ctx.lineTo(Math.cos(-Math.PI/2+rollA)*(rollR+4), Math.sin(-Math.PI/2+rollA)*(rollR+4))
  ctx.stroke()
  ctx.restore()

  // readout
  ctx.fillStyle = '#cdd3de'; ctx.font = '10px monospace'; ctx.textAlign = 'center'
  ctx.fillText('R ' + fmt1(S.roll) + '°  P ' + fmt1(S.pitch) + '°', cx, cy+R+14)
}

function drawCompass () {
  const canvas = $('compass-canvas')
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  const cx = W/2, cy = H/2, R = Math.min(W,H)*0.40

  ctx.clearRect(0,0,W,H)

  // background circle
  ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2)
  ctx.fillStyle = '#161a22'; ctx.fill()
  ctx.strokeStyle = '#3a4050'; ctx.lineWidth = 1.5; ctx.stroke()

  // cardinal labels
  const cardinals = ['N','NE','E','SE','S','SW','W','NW']
  cardinals.forEach((c,i) => {
    const a = (i/8)*Math.PI*2 - Math.PI/2
    const r = R - 16
    ctx.fillStyle = c === 'N' ? '#e04040' : '#5a6072'
    ctx.font = (c.length === 1 ? 'bold 11px' : '9px') + ' sans-serif'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(c, cx+Math.cos(a)*r, cy+Math.sin(a)*r)
  })

  // degree ticks
  for (let d = 0; d < 360; d += 5) {
    const a   = d*DEG - Math.PI/2
    const len = d % 30 === 0 ? 10 : 5
    ctx.beginPath()
    ctx.moveTo(cx+Math.cos(a)*(R-2),   cy+Math.sin(a)*(R-2))
    ctx.lineTo(cx+Math.cos(a)*(R-len), cy+Math.sin(a)*(R-len))
    ctx.strokeStyle = d % 30 === 0 ? '#4a5060' : '#2a2f3a'; ctx.lineWidth = 1; ctx.stroke()
  }

  // heading needle
  const ha = S.heading*DEG - Math.PI/2
  ctx.beginPath()
  ctx.moveTo(cx, cy)
  ctx.lineTo(cx+Math.cos(ha)*(R-20), cy+Math.sin(ha)*(R-20))
  ctx.strokeStyle = '#e04040'; ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.stroke()

  // tail
  ctx.beginPath()
  ctx.moveTo(cx, cy)
  ctx.lineTo(cx-Math.cos(ha)*18, cy-Math.sin(ha)*18)
  ctx.strokeStyle = '#4d9fff'; ctx.lineWidth = 2; ctx.stroke()

  // center dot
  ctx.beginPath(); ctx.arc(cx,cy,4,0,Math.PI*2)
  ctx.fillStyle = '#cdd3de'; ctx.fill()

  // heading text
  ctx.fillStyle = '#cdd3de'; ctx.font = 'bold 14px monospace'; ctx.textAlign = 'center'
  ctx.fillText(Math.round(S.heading)+'°', cx, cy+R+14)
}

function drawChart (canvasId, history, color, unit, maxVal) {
  const canvas = $(canvasId)
  if (!canvas) return
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext('2d')
  ctx.clearRect(0,0,W,H)
  ctx.fillStyle = '#0f1318'; ctx.fillRect(0,0,W,H)

  if (history.length < 2) return

  const pad = { t:14, b:18, l:32, r:8 }
  const gW  = W - pad.l - pad.r
  const gH  = H - pad.t - pad.b

  const max = maxVal || Math.max(...history, 1)
  const min = Math.min(...history, 0)
  const range = max - min || 1

  // grid lines
  ctx.strokeStyle = '#1e2530'; ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (i/4)*gH
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W-pad.r, y); ctx.stroke()
    const v = max - (i/4)*range
    ctx.fillStyle = '#4a5060'; ctx.font = '9px monospace'; ctx.textAlign = 'right'
    ctx.fillText(v.toFixed(1), pad.l-3, y+3)
  }

  // line
  ctx.beginPath()
  history.forEach((v, i) => {
    const x = pad.l + (i/(HIST_MAX-1))*gW
    const y = pad.t + (1-(v-min)/range)*gH
    i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y)
  })
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke()

  // fill
  ctx.lineTo(pad.l + ((history.length-1)/(HIST_MAX-1))*gW, pad.t+gH)
  ctx.lineTo(pad.l, pad.t+gH)
  ctx.closePath()
  ctx.fillStyle = color.replace(')',', 0.15)').replace('rgb','rgba').replace('#', 'rgba(').concat(')')
  // simple fill with low opacity
  ctx.globalAlpha = 0.12; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1

  // current value label
  const last = history[history.length-1]
  ctx.fillStyle = color; ctx.font = 'bold 11px monospace'; ctx.textAlign = 'right'
  ctx.fillText(fmt1(last) + (unit?' '+unit:''), W-pad.r, pad.t-3)
}

function updateSlamPoseUI () {
  $('sl-x').textContent     = fmt2(S.slamPose.x) + ' m'
  $('sl-y').textContent     = fmt2(S.slamPose.y) + ' m'
  $('sl-theta').textContent = fmt1(S.slamPose.theta) + '°'
}

// Decode PointCloud2 binary → packed Float32Array [x,y,z, x,y,z, ...] — no subsampling
function decodePC2xyz (msg) {
  const raw = atob(msg.data)
  const buf = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
  let xOff = 0, yOff = 4, zOff = 8
  if (msg.fields) msg.fields.forEach(f => {
    if (f.name === 'x') xOff = f.offset
    if (f.name === 'y') yOff = f.offset
    if (f.name === 'z') zOff = f.offset
  })
  const step = msg.point_step || 26
  const count = (msg.width || 0) * (msg.height || 1)
  const le = !msg.is_bigendian
  const dv = new DataView(buf.buffer)
  const out = new Float32Array(count * 3)
  let n = 0
  for (let i = 0; i < count; i++) {
    const b = i * step
    if (b + zOff + 4 > buf.length) break
    const x = dv.getFloat32(b + xOff, le)
    const y = dv.getFloat32(b + yOff, le)
    const z = dv.getFloat32(b + zOff, le)
    if (isFinite(x) && isFinite(y) && isFinite(z)) {
      out[n++] = x; out[n++] = y; out[n++] = z
    }
  }
  return { data: out, count: n / 3 }
}

// ── SLAM 3D WebGL point-cloud renderer (Point-LIO / Unitree L2) ──────────────
const SLAM3D = (() => {
  const MAX = 800000   // ring-buffer capacity (~11 min at 1200 pts/s)
  let gl = null, prog = null, bufPos = null, bufCol = null
  let uMVP = -1, uSz = -1, aPos = -1, aCol = -1
  const posArr = new Float32Array(MAX * 3)
  const colArr = new Float32Array(MAX * 3)
  let total = 0, ready = false

  const cam = { theta: 0.4, phi: 0.42, dist: 12, tx: 0, ty: 0, tz: 0 }
  let drag = null

  const VS = `attribute vec3 aPos;attribute vec3 aCol;
    uniform mat4 uMVP;uniform float uSz;varying vec3 vCol;
    void main(){gl_Position=uMVP*vec4(aPos,1.);
      gl_PointSize=max(1.,uSz/gl_Position.w);vCol=aCol;}`
  const FS = `precision mediump float;varying vec3 vCol;
    void main(){vec2 c=gl_PointCoord-.5;if(dot(c,c)>.25)discard;
      gl_FragColor=vec4(vCol,1.);}`

  function mkShader (src, type) {
    const s = gl.createShader(type)
    gl.shaderSource(s, src); gl.compileShader(s); return s
  }

  // RViz2-style rainbow: blue(low) → cyan → green → yellow → red(high)
  function hcol (z) {
    const t = Math.max(0, Math.min(1, (z + 0.5) / 3.0))
    if (t < 0.25) return [0,        t * 4,          1]
    if (t < 0.5)  return [0,        1,               1 - (t - 0.25) * 4]
    if (t < 0.75) return [(t-0.5)*4, 1,              0]
    return              [1,          1-(t-0.75)*4,   0]
  }

  function mul4 (A, B) {
    const C = new Float32Array(16)
    for (let c = 0; c < 4; c++)
      for (let r = 0; r < 4; r++)
        for (let k = 0; k < 4; k++) C[c*4+r] += A[k*4+r] * B[c*4+k]
    return C
  }

  function persp (fov, asp, n, f) {
    const t = 1 / Math.tan(fov / 2)
    return new Float32Array([
      t/asp, 0,  0,                    0,
      0,     t,  0,                    0,
      0,     0, (f+n)/(n-f),          -1,
      0,     0, (2*f*n)/(n-f),         0,
    ])
  }

  function lookAt (ex, ey, ez, tx, ty, tz) {
    let fx=tx-ex, fy=ty-ey, fz=tz-ez
    const fl = Math.hypot(fx,fy,fz)||1; fx/=fl; fy/=fl; fz/=fl
    // right = cross(forward, Z-up) = [fy, -fx, 0]
    let rx=fy, ry=-fx, rz=0
    const rl = Math.hypot(rx,ry)||1; rx/=rl; ry/=rl
    // true up = cross(right, forward)
    const ux=ry*fz-rz*fy, uy=rz*fx-rx*fz, uz=rx*fy-ry*fx
    return new Float32Array([
      rx, ux, -fx, 0,  ry, uy, -fy, 0,  rz, uz, -fz, 0,
      -(rx*ex+ry*ey+rz*ez), -(ux*ex+uy*ey+uz*ez), fx*ex+fy*ey+fz*ez, 1,
    ])
  }

  function mvpMat (W, H) {
    const cP = Math.cos(cam.phi), sP = Math.sin(cam.phi)
    const cT = Math.cos(cam.theta), sT = Math.sin(cam.theta)
    const ex = cam.tx + cam.dist * cP * cT
    const ey = cam.ty + cam.dist * cP * sT
    const ez = cam.tz + cam.dist * sP
    return mul4(persp(60*DEG, W/H, 0.05, 500), lookAt(ex,ey,ez, cam.tx,cam.ty,cam.tz))
  }

  function init (canvas) {
    if (ready) return true
    gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) return false
    prog = gl.createProgram()
    gl.attachShader(prog, mkShader(VS, gl.VERTEX_SHADER))
    gl.attachShader(prog, mkShader(FS, gl.FRAGMENT_SHADER))
    gl.linkProgram(prog); gl.useProgram(prog)
    bufPos = gl.createBuffer(); bufCol = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos)
    gl.bufferData(gl.ARRAY_BUFFER, posArr, gl.DYNAMIC_DRAW)
    gl.bindBuffer(gl.ARRAY_BUFFER, bufCol)
    gl.bufferData(gl.ARRAY_BUFFER, colArr, gl.DYNAMIC_DRAW)
    uMVP = gl.getUniformLocation(prog, 'uMVP')
    uSz  = gl.getUniformLocation(prog, 'uSz')
    aPos = gl.getAttribLocation(prog,  'aPos')
    aCol = gl.getAttribLocation(prog,  'aCol')
    gl.enableVertexAttribArray(aPos)
    gl.enableVertexAttribArray(aCol)
    gl.enable(gl.DEPTH_TEST)
    gl.clearColor(0.04, 0.055, 0.078, 1)

    canvas.addEventListener('mousedown', e => { drag = { x: e.clientX, y: e.clientY, btn: e.button } })
    window.addEventListener('mouseup', () => { drag = null })
    canvas.addEventListener('mousemove', e => {
      if (!drag) return
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y
      if (drag.btn === 0) {
        cam.theta -= dx * 0.006
        cam.phi = Math.max(-1.4, Math.min(1.4, cam.phi - dy * 0.006))
      } else {
        const s = cam.dist * 0.0015
        cam.tx -= dx * s * Math.cos(cam.theta)
        cam.ty -= dx * s * Math.sin(cam.theta)
        cam.tz += dy * s
      }
      drag.x = e.clientX; drag.y = e.clientY
    })
    canvas.addEventListener('wheel', e => {
      cam.dist = Math.max(0.3, Math.min(300, cam.dist * (1 + e.deltaY * 0.001)))
      e.preventDefault()
    }, { passive: false })
    canvas.addEventListener('contextmenu', e => e.preventDefault())
    ready = true; return true
  }

  function addScan (scan) {
    // Always accumulate into CPU arrays (even before WebGL is ready)
    for (let i = 0; i < scan.count; i++) {
      const slot = (total % MAX) * 3
      const si   = i * 3
      posArr[slot]   = scan.data[si]
      posArr[slot+1] = scan.data[si+1]
      posArr[slot+2] = scan.data[si+2]
      const [r,g,b]  = hcol(scan.data[si+2])
      colArr[slot] = r; colArr[slot+1] = g; colArr[slot+2] = b
      total++
    }
    // Upload to GPU only if WebGL context exists
    if (!ready) return
    const used = Math.min(total, MAX) * 3
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos)
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, posArr.subarray(0, used))
    gl.bindBuffer(gl.ARRAY_BUFFER, bufCol)
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, colArr.subarray(0, used))
  }

  function render (canvas) {
    if (!ready) return
    const W = canvas.width, H = canvas.height
    if (W < 2 || H < 2) return
    gl.viewport(0, 0, W, H)
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
    const used = Math.min(total, MAX)
    if (used === 0) return
    gl.uniformMatrix4fv(uMVP, false, mvpMat(W, H))
    gl.uniform1f(uSz, Math.max(2, 60 / cam.dist))
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos)
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0)
    gl.bindBuffer(gl.ARRAY_BUFFER, bufCol)
    gl.vertexAttribPointer(aCol, 3, gl.FLOAT, false, 0, 0)
    gl.drawArrays(gl.POINTS, 0, used)
  }

  function clearMap () {
    total = 0
    posArr.fill(0); colArr.fill(0)
    if (ready) {
      gl.bindBuffer(gl.ARRAY_BUFFER, bufPos); gl.bufferData(gl.ARRAY_BUFFER, posArr, gl.DYNAMIC_DRAW)
      gl.bindBuffer(gl.ARRAY_BUFFER, bufCol); gl.bufferData(gl.ARRAY_BUFFER, colArr, gl.DYNAMIC_DRAW)
    }
  }

  return { init, addScan, render, clearMap, cam, get count () { return Math.min(total, MAX) } }
})()

function drawSLAM () {
  const canvas = $('slam-canvas')
  const wrap   = $('slam-main')
  if (!canvas || !wrap) return

  // Resize only when container dimensions change
  const W = wrap.clientWidth, H = wrap.clientHeight - 26
  if (W < 2 || H < 2) return
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W; canvas.height = H
  }

  if (!SLAM3D.init(canvas)) return   // fallback if no WebGL

  SLAM3D.render(canvas)

  // Overlay: pose + instructions via 2D canvas on top if no points yet
  if (SLAM3D.count === 0) {
    const ctx2 = canvas.getContext('2d')
    if (ctx2) {
      ctx2.fillStyle = 'rgba(42,48,64,.85)'
      ctx2.fillRect(W/2-200, H/2-30, 400, 60)
      ctx2.fillStyle = '#5a6072'; ctx2.font = '13px sans-serif'; ctx2.textAlign = 'center'
      ctx2.fillText('Waiting for /cloud_registered…', W/2, H/2-8)
      ctx2.fillStyle = '#3a4050'; ctx2.font = '11px sans-serif'
      ctx2.fillText('ros2 launch point_lio mapping_unilidar_l2.launch.py', W/2, H/2+14)
    }
  }
}

// Test pattern for cameras without a live feed
function drawTestPattern (canvasId, hue) {
  const canvas = $(canvasId)
  if (!canvas) return
  const parent = canvas.parentElement
  const W = parent ? parent.clientWidth  || 640 : 640
  const H = parent ? parent.clientHeight || 360 : 360
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')
  const bars = [0, 60, 120, 180, 240, 300, 360, 'white', 'black']
  const bw   = W / bars.length
  bars.forEach((h, i) => {
    ctx.fillStyle = typeof h === 'string' ? h : `hsl(${(h+hue)%360},80%,50%)`
    ctx.fillRect(i*bw, 0, bw, H*0.72)
  })
  const g = ctx.createLinearGradient(0,0,W,0)
  g.addColorStop(0,'#000'); g.addColorStop(1,'#fff')
  ctx.fillStyle = g; ctx.fillRect(0, H*0.72, W, H*0.28)
  ctx.fillStyle = 'rgba(0,0,0,.5)'; ctx.fillRect(W/2-90,H/2-16,180,32)
  ctx.fillStyle = '#fff'; ctx.font = 'bold 12px monospace'; ctx.textAlign = 'center'
  ctx.fillText('NO VIDEO SIGNAL', W/2, H/2+4)
}

// ── canvas resize ─────────────────────────────────────────────────────────────
function resizeCanvases () {
  const ro = new ResizeObserver(() => {
    ;['cam1','icam1','icam2','horizon-canvas','compass-canvas',
      'chart-alt','chart-spd','chart-vspd','hex-diagram'].forEach(id => {
      const c = $(id)
      if (!c || !c.parentElement) return
      c.width  = c.offsetWidth  || c.parentElement.clientWidth
      c.height = c.offsetHeight || c.parentElement.clientHeight
    })
    drawMap()
    drawSLAM()
  })
  ;['cam-col','hex-block','img-left','img-cams','nav-top','nav-charts','slam-main'].forEach(id => {
    const el = $(id)
    if (el) ro.observe(el)
  })
}

// ── main animation loop ───────────────────────────────────────────────────────
function frame () {
  updateDOM()
  drawSpeedometer()
  drawBatteryArc()
  drawHexDiagram()
  drawMap()

  if (S.activeView === 'navigation') {
    drawHorizon()
    drawCompass()
    drawChart('chart-alt',  S.altHistory,  '#4d9fff', 'm')
    drawChart('chart-spd',  S.spdHistory,  '#3ddc84', 'm/s')
    drawChart('chart-vspd', S.vspdHistory, '#f0a500', 'm/s')
  }
  if (S.activeView === 'slam') {
    drawSLAM()
  }

  requestAnimationFrame(frame)
}

// ── boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  drawTestPattern('cam1',  0)
  drawTestPattern('icam1', 0)
  drawTestPattern('icam2', 120)
  resizeCanvases()
  initConnPopover()
  initControls()
  connect()
  frame()
})
