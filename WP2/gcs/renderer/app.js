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
  loopClosures: 0,
  altHistory: [], spdHistory: [], vspdHistory: [],
  flightStart: null,
  activeView: 'dashboard',
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
let ROS_URL = localStorage.getItem('ros_url') || 'ws://localhost:9090'
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

// ── subscriptions ─────────────────────────────────────────────────────────────
function subscribe () {
  // speed + heading
  sub('/mavros/vfr_hud', 'mavros_msgs/VFR_HUD', m => {
    S.speed   = m.airspeed   ?? 0
    S.vspeed  = m.climb      ?? 0
    S.heading = m.heading    ?? 0
    pushHist(S.spdHistory,  S.speed)
    pushHist(S.vspdHistory, S.vspeed)
  })

  // altitude
  sub('/mavros/altitude', 'mavros_msgs/Altitude', m => {
    S.altitude = m.relative ?? m.monotonic ?? 0
    pushHist(S.altHistory, S.altitude)
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
    if (S.trail.length === 0 ||
        Math.abs(S.trail[S.trail.length-1].lat - m.latitude)  > 1e-7 ||
        Math.abs(S.trail[S.trail.length-1].lon - m.longitude) > 1e-7) {
      S.trail.push({ lat: m.latitude, lon: m.longitude })
      if (S.trail.length > 500) S.trail.shift()
    }
  })

  // GPS status
  sub('/mavros/gpsstatus', 'mavros_msgs/GPSRAW', m => {
    S.gps.fix  = m.fix_type ?? 0
    S.gps.sats = m.satellites_visible ?? 0
  })

  // state (armed / mode)
  sub('/mavros/state', 'mavros_msgs/State', m => {
    if (m.armed && !S.armed) S.flightStart = Date.now()
    if (!m.armed) S.flightStart = null
    S.armed = m.armed
    S.mode  = m.mode || '—'
  })

  // motor throttle (PWM 1000-2000 → 0-100 %)
  sub('/mavros/rc/out', 'mavros_msgs/RCOut', m => {
    const ch = m.channels || []
    for (let i = 0; i < 6; i++) {
      const pwm = ch[i] ?? 1000
      S.motors[i] = clamp((pwm - 1000) / 1000 * 100, 0, 100)
    }
  })

  // LiDAR scan
  sub('/scan', 'sensor_msgs/LaserScan', m => {
    S.lidar = m
    $('sl-pts').textContent   = m.ranges.length
    $('sl-minr').textContent  = fmt2(m.range_min) + ' m'
    $('sl-maxr').textContent  = fmt2(m.range_max) + ' m'
    $('sl-astep').textContent = fmt2(m.angle_increment * R2D) + '°'
    $('sl-status').textContent = 'Active'
    $('sl-status').className   = 'sv ok'
  })

  // Occupancy grid
  sub('/map', 'nav_msgs/OccupancyGrid', m => {
    S.occMap = m
    $('sl-mw').textContent  = m.info.width + ' cells'
    $('sl-mh').textContent  = m.info.height + ' cells'
    $('sl-res').textContent = fmt2(m.info.resolution) + ' m/cell'
    $('sl-ox').textContent  = fmt2(m.info.origin.position.x) + ' m'
    $('sl-oy').textContent  = fmt2(m.info.origin.position.y) + ' m'
  })

  // SLAM pose
  sub('/slam_toolbox/pose', 'geometry_msgs/PoseWithCovarianceStamped', m => {
    const p = m.pose.pose
    S.slamPose.x     = p.position.x
    S.slamPose.y     = p.position.y
    const q = p.orientation
    S.slamPose.theta = Math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z)) * R2D
    $('sl-x').textContent     = fmt2(S.slamPose.x) + ' m'
    $('sl-y').textContent     = fmt2(S.slamPose.y) + ' m'
    $('sl-theta').textContent = fmt1(S.slamPose.theta) + '°'
  })

  // Barcode detection (std_msgs/String carrying JSON or plain barcode string)
  sub('/barcode/detection', 'std_msgs/String', m => {
    let code = m.data, status = 'OK'
    try { const j = JSON.parse(m.data); code = j.barcode || j.code || m.data; status = j.status || 'OK' } catch (_) {}
    const entry = { code, status, time: now() }
    S.barcodes.unshift(entry)
    if (S.barcodes.length > 50) S.barcodes.pop()
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
  subCamImage('/camera/forward/image_raw/compressed',  'cam1',  'cam1-sig')
  subCamImage('/camera/forward/image_raw/compressed',  'icam1', 'icam1-sig')
  subCamImage('/camera/down/image_raw/compressed',     'icam2', 'icam2-sig')
}

// Subscribe to a compressed image topic and draw to a canvas by id
function subCamImage (topic, canvasId, sigId) {
  if (!canvasId) return
  sub(topic, 'sensor_msgs/CompressedImage', m => {
    const canvas = $(canvasId)
    if (!canvas) return
    // Decode base64 → Uint8Array → Blob → ImageBitmap (off-main-thread decode)
    try {
      const raw  = atob(m.data)
      const buf  = new Uint8Array(raw.length)
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
      const blob = new Blob([buf], { type: 'image/jpeg' })
      createImageBitmap(blob).then(bitmap => {
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)
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
  $('val-alt').textContent     = fmt1(S.altitude)
  $('val-hdg').textContent     = Math.round(S.heading)
  $('val-bat').textContent     = S.battery.pct > 0 ? Math.round(S.battery.pct) : '—'
  $('val-volt').textContent    = S.battery.voltage > 0 ? fmt2(S.battery.voltage) + ' V' : '— V'
  $('val-lat').textContent     = fmt6(S.gps.lat)
  $('val-lon').textContent     = fmt6(S.gps.lon)
  $('val-alt-abs').textContent = fmt1(S.gps.altAbs)
  $('val-sats').textContent    = S.gps.sats || '—'

  const altBarPct = clamp(S.altitude / 120 * 100, 0, 100)
  $('bar-alt').style.width = altBarPct + '%'

  const pillArm  = $('pill-arm')
  pillArm.textContent = S.armed ? 'ARMED' : 'DISARMED'
  pillArm.className   = 'pill' + (S.armed ? ' armed' : '')
  const pillMode = $('pill-mode')
  pillMode.textContent = S.mode
  pillMode.className   = 'pill active'

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
  $('db-count').textContent = S.barcodes.length + ' record' + (S.barcodes.length !== 1 ? 's' : '')
  const last = S.barcodes[0]
  if (last) {
    const el = $('db-last-code')
    el.textContent = last.code
    el.className   = 'bc-badge bc-new'
    setTimeout(() => el.classList.remove('bc-new'), 900)
  }
  const tbody = $('db-tbody')
  tbody.innerHTML = ''
  S.barcodes.slice(0, 20).forEach(r => {
    const tr = document.createElement('tr')
    tr.innerHTML = `<td style="font-family:monospace">${r.code}</td><td style="color:var(--muted)">${r.time}</td><td class="db-ok">${r.status}</td>`
    tbody.appendChild(tr)
  })
}

function updateDetectTable () {
  const tbody = $('detect-tbody')
  tbody.innerHTML = ''
  S.detections.slice(0, 30).forEach(d => {
    const tr = document.createElement('tr')
    tr.innerHTML = `<td>${d.label}</td><td style="font-family:monospace">${d.id}</td><td style="color:var(--ok)">${d.conf}</td><td style="color:var(--muted)">${d.time}</td>`
    tbody.appendChild(tr)
  })
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
  const reach = Math.min(W, H) * 0.365  // distance center → motor center (px)
  const scale = reach / 0.5             // converts PX4 unit coords → px
  const mR    = 17                       // motor arc radius
  const SA = 225 * DEG, TA = 270 * DEG

  // Motor positions: sx=Y_right, sy=-X_fwd (matches QGC actuator layout)
  // CCW per QGC table: motors 2, 4, 5 are CCW
  const MOTORS = [
    { n:1, sx: 0.50, sy: 0.00, ccw:false },
    { n:2, sx:-0.50, sy: 0.00, ccw:true  },
    { n:3, sx:-0.25, sy:-0.43, ccw:false },
    { n:4, sx: 0.25, sy: 0.43, ccw:true  },
    { n:5, sx: 0.25, sy:-0.43, ccw:true  },
    { n:6, sx:-0.25, sy: 0.43, ccw:false },
  ]

  // 1. Arms (behind everything)
  ctx.lineWidth = 3
  MOTORS.forEach(m => {
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + m.sx * scale, cy + m.sy * scale)
    ctx.strokeStyle = '#3a4050'; ctx.stroke()
  })

  // 2. Motor nodes with thrust arc gauges
  MOTORS.forEach(m => {
    const pct  = S.motors[m.n - 1] || 0
    const mx   = cx + m.sx * scale
    const my   = cy + m.sy * scale
    const idle = m.ccw ? '#4d9fff' : '#3ddc84'
    const col  = pct < 60 ? '#3ddc84' : pct < 80 ? '#f0a500' : '#e04040'
    const ring = pct > 0 ? col : idle

    // Background disc
    ctx.beginPath(); ctx.arc(mx, my, mR + 3, 0, Math.PI * 2)
    ctx.fillStyle = '#161b24'; ctx.fill()

    // Arc track
    ctx.beginPath(); ctx.arc(mx, my, mR, SA, SA + TA)
    ctx.strokeStyle = '#2a2f3a'; ctx.lineWidth = 5; ctx.lineCap = 'round'; ctx.stroke()

    // Thrust arc
    if (pct > 0) {
      ctx.beginPath(); ctx.arc(mx, my, mR, SA, SA + (pct / 100) * TA)
      ctx.strokeStyle = col; ctx.lineWidth = 5; ctx.lineCap = 'round'; ctx.stroke()
    }

    // Rotation-direction colour ring
    ctx.beginPath(); ctx.arc(mx, my, mR + 1.5, 0, Math.PI * 2)
    ctx.strokeStyle = ring; ctx.lineWidth = 1.5; ctx.stroke()

    // Labels: motor number + thrust %
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillStyle = idle; ctx.font = 'bold 8px monospace'
    ctx.fillText('M' + m.n, mx, my - 5)
    ctx.fillStyle = pct > 0 ? col : '#5a6072'; ctx.font = 'bold 8px monospace'
    ctx.fillText(Math.round(pct) + '%', mx, my + 5)
  })

  // 3. Central body (over arm roots)
  ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2)
  ctx.fillStyle = '#555c6e'; ctx.fill()
  ctx.strokeStyle = '#8a93a8'; ctx.lineWidth = 1.5; ctx.stroke()

  // Forward indicator (red triangle = nose direction)
  ctx.beginPath()
  ctx.moveTo(cx, cy - 6); ctx.lineTo(cx - 4, cy + 3); ctx.lineTo(cx + 4, cy + 3)
  ctx.closePath(); ctx.fillStyle = '#e04040'; ctx.fill()
}

function drawMap () {
  const canvas = $('map-canvas')
  const wrap   = $('map-wrap')
  if (!canvas || !wrap) return
  const W = wrap.clientWidth, H = wrap.clientHeight - 24  // subtract ph height
  if (W < 10 || H < 10) return
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')

  ctx.fillStyle = '#0d1520'; ctx.fillRect(0,0,W,H)

  // grid
  ctx.strokeStyle = '#162030'; ctx.lineWidth = 1
  const step = 40
  for (let x = 0; x < W; x += step) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke() }
  for (let y = 0; y < H; y += step) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke() }

  // compass labels
  ctx.fillStyle = '#2e3a4a'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center'
  ctx.fillText('N', W/2, 12); ctx.fillText('S', W/2, H-4)
  ctx.textAlign = 'left';  ctx.fillText('W', 4,   H/2+4)
  ctx.textAlign = 'right'; ctx.fillText('E', W-4, H/2+4)

  if (!S.gps.lat) {
    ctx.fillStyle = '#5a6072'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('Awaiting GPS…', W/2, H/2); return
  }

  const cx = W/2, cy = H/2
  const scale = Math.min(W,H) / 2 / 0.0018  // ~200 m radius
  const proj  = (lat, lon) => ({
    x: cx + (lon - S.gps.lon) * scale,
    y: cy - (lat - S.gps.lat) * scale,
  })

  // trail
  if (S.trail.length > 1) {
    ctx.beginPath()
    S.trail.forEach((pt, i) => {
      const p = proj(pt.lat, pt.lon)
      i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)
    })
    ctx.strokeStyle = 'rgba(77,159,255,.5)'; ctx.lineWidth = 1.5; ctx.stroke()
  }

  // home cross
  if (S.trail.length > 0) {
    const h = proj(S.trail[0].lat, S.trail[0].lon)
    ctx.strokeStyle = '#3ddc84'; ctx.lineWidth = 1.5
    ctx.beginPath(); ctx.moveTo(h.x-6,h.y); ctx.lineTo(h.x+6,h.y); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(h.x,h.y-6); ctx.lineTo(h.x,h.y+6); ctx.stroke()
  }

  // drone marker
  ctx.beginPath(); ctx.arc(cx,cy,6,0,Math.PI*2)
  ctx.fillStyle = '#4d9fff'; ctx.fill()
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()

  // heading ray
  const ha = (S.heading - 90) * DEG
  ctx.beginPath()
  ctx.moveTo(cx, cy)
  ctx.lineTo(cx + Math.cos(ha)*18, cy + Math.sin(ha)*18)
  ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 1.5; ctx.stroke()
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

function drawSLAM () {
  const canvas = $('slam-canvas')
  const wrap   = $('slam-main')
  if (!canvas || !wrap) return
  const W = wrap.clientWidth, H = wrap.clientHeight - 26
  if (W < 10 || H < 10) return
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')

  ctx.fillStyle = '#0a0e14'; ctx.fillRect(0,0,W,H)

  const cx = W/2, cy = H/2

  // occupancy grid
  if (S.occMap) {
    const { info, data } = S.occMap
    const cellPx = Math.min(W / info.width, H / info.height)
    const offX = cx - (info.width  * cellPx) / 2
    const offY = cy - (info.height * cellPx) / 2
    for (let r = 0; r < info.height; r++) {
      for (let c = 0; c < info.width; c++) {
        const v = data[r * info.width + c]
        if (v < 0) continue
        ctx.fillStyle = v === 0 ? '#1a2030' : `rgb(${255-v*2},${255-v*2},${255-v*2})`
        ctx.fillRect(offX + c*cellPx, offY + (info.height-1-r)*cellPx, cellPx, cellPx)
      }
    }
  } else {
    // placeholder grid
    ctx.strokeStyle = '#162030'; ctx.lineWidth = 1
    for (let x = 0; x < W; x += 30) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke() }
    for (let y = 0; y < H; y += 30) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke() }
    ctx.fillStyle = '#2a3040'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('Waiting for /map topic…', cx, cy-10)
  }

  // LiDAR scan overlay
  if (S.lidar) {
    const m      = S.lidar
    const scale  = 60            // px per metre
    const ox     = cx + S.slamPose.x * scale
    const oy     = cy - S.slamPose.y * scale
    const theta  = S.slamPose.theta * DEG

    ctx.save()
    ctx.translate(ox, oy)
    ctx.rotate(theta)
    ctx.fillStyle = 'rgba(77,159,255,.7)'
    m.ranges.forEach((r, i) => {
      if (!isFinite(r) || r < m.range_min || r > m.range_max) return
      const a = m.angle_min + i * m.angle_increment
      const px = Math.cos(a) * r * scale
      const py = -Math.sin(a) * r * scale
      ctx.beginPath(); ctx.arc(px, py, 1.5, 0, Math.PI*2); ctx.fill()
    })
    ctx.restore()

    // robot marker
    ctx.beginPath(); ctx.arc(ox, oy, 7, 0, Math.PI*2)
    ctx.fillStyle = '#4d9fff'; ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()
    // heading ray
    const ra = theta - Math.PI/2
    ctx.beginPath(); ctx.moveTo(ox,oy)
    ctx.lineTo(ox+Math.cos(ra)*20, oy+Math.sin(ra)*20)
    ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 2; ctx.stroke()
  } else {
    ctx.fillStyle = '#3a4050'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('Waiting for /scan topic…', cx, cy+20)
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
      'chart-alt','chart-spd','chart-vspd'].forEach(id => {
      const c = $(id)
      if (!c || !c.parentElement) return
      const p = c.parentElement
      c.width  = p.clientWidth
      c.height = p.clientHeight
    })
    drawMap()
    drawSLAM()
  })
  ;['cam-col','img-left','img-cams','nav-top','nav-charts','slam-main'].forEach(id => {
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
  connect()
  frame()
})
