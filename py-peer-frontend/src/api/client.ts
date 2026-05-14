// ─── Types ────────────────────────────────────────────────────────────────────

export interface ApiResponse<T> {
  success: boolean
  data: T
  error: { code: number; message: string; detail: string | null } | null
  timestamp: number
}

export interface NodeInfo {
  peer_id: string
  nickname: string
  multiaddr: string
  port: number
  ready: boolean
  uptime_seconds: number
}

export interface ServiceStatus {
  ready: boolean
  running: boolean
  uptime_seconds: number
  peer_count: number
}

export interface ServiceConfig {
  nickname: string
  port: number
  topic: string | null
  strict_signing: boolean
  download_dir: string
  connect_addrs: string[]
}

export interface TopicInfo {
  unread_count: number
  total_count: number
  last_message: ChatMessage | null
}

export interface ChatMessage {
  type: 'chat_message' | 'file_message' | 'file_shared' | 'file_downloaded'
  message?: string
  sender_nick: string
  sender_id: string
  timestamp: number
  topic: string
  read: boolean
  file_cid?: string
  file_name?: string
  file_size?: number
}

export interface DirectMessage {
  type: 'dm'
  message: string
  sender_nick: string
  sender_id: string
  timestamp: number
  peer_id: string
  read: boolean
  outgoing?: boolean
}

export interface PubSubConfig {
  degree: number
  degree_low: number
  degree_high: number
  heartbeat_interval: number
  protocols: string[]
}

export interface DHTStatus {
  mode: string
  random_walk_enabled: boolean
  routing_table_size: number
}

// ─── Base URL ─────────────────────────────────────────────────────────────────
// In development the Vite proxy forwards /api/* → localhost:8765, so VITE_API_URL
// can be left empty.  In production (Vercel / Netlify) set it to your backend's
// full origin, e.g.  VITE_API_URL=https://your-backend.example.com

const API_ORIGIN: string = import.meta.env.VITE_API_URL ?? ''
export const BASE = `${API_ORIGIN}/api/v1`

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  const json: ApiResponse<T> = await res.json()
  if (!json.success) throw new Error(json.error?.message ?? 'API error')
  return json.data
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const json: ApiResponse<T> = await res.json()
  if (!json.success) throw new Error(json.error?.message ?? 'API error')
  return json.data
}

async function put<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'PUT' })
  const json: ApiResponse<T> = await res.json()
  if (!json.success) throw new Error(json.error?.message ?? 'API error')
  return json.data
}

// ─── Node ─────────────────────────────────────────────────────────────────────

export const getNodeInfo = () => get<NodeInfo>('/node/info')
export const getServiceStatus = () => get<ServiceStatus>('/service/status')
export const getServiceConfig = () => get<ServiceConfig>('/service/config')

// ─── Peers ────────────────────────────────────────────────────────────────────

export const getPeers = () => get<{ peers: string[]; count: number }>('/peers')
export const getKnownPeers = () => get<{ peers: string[]; count: number }>('/peers/known')
export const connectToPeer = (multiaddr: string) =>
  post<{ message: string; multiaddr: string }>('/peers/connect', { multiaddr })

// ─── Topics ───────────────────────────────────────────────────────────────────

export const getTopics = () =>
  get<{ topics: Record<string, TopicInfo>; count: number }>('/topics')
export const subscribeTopic = (topic: string) =>
  post<{ message: string; topic: string }>('/topics', { topic })

// ─── Messages ─────────────────────────────────────────────────────────────────

export const getMessages = (topic: string, limit = 100, offset = 0) =>
  get<{ messages: ChatMessage[]; total: number; limit: number; offset: number }>(
    `/messages/${encodeURIComponent(topic)}?limit=${limit}&offset=${offset}`,
  )
export const sendMessage = (topic: string, message: string) =>
  post<{ message: string; topic: string }>(`/messages/${encodeURIComponent(topic)}`, { message })
export const getUnread = (topic: string) =>
  get<{ unread_count: number }>(`/messages/${encodeURIComponent(topic)}/unread`)
export const markRead = (topic: string) =>
  put<{ message: string }>(`/messages/${encodeURIComponent(topic)}/read`)

// ─── Direct Messages ──────────────────────────────────────────────────────────

export const sendDM = (peerId: string, message: string) =>
  post<{ message: string; peer_id: string }>(`/dm/${encodeURIComponent(peerId)}`, { message })

export const getDMHistory = (peerId: string, limit = 100, offset = 0) =>
  get<{ peer_id: string; messages: DirectMessage[]; total: number; limit: number; offset: number }>(
    `/dm/${encodeURIComponent(peerId)}?limit=${limit}&offset=${offset}`,
  )

export const getDMUnread = (peerId: string) =>
  get<{ peer_id: string; unread_count: number }>(`/dm/${encodeURIComponent(peerId)}/unread`)

export const markDMRead = (peerId: string) =>
  put<{ message: string }>(`/dm/${encodeURIComponent(peerId)}/read`)

// ─── Payment Keys ─────────────────────────────────────────────────────────────

export const setMyPaymentKey = (paymentKey: string) =>
  post<{ message: string; payment_key: string }>('/dm/payment-key', { payment_key: paymentKey })

export const getAllPaymentKeys = () =>
  get<{ my_payment_key: string; peer_keys: Record<string, string>; count: number }>('/dm/payment-keys')

export const getPeerPaymentKey = (peerId: string) =>
  get<{ peer_id: string; payment_key: string }>(`/dm/${encodeURIComponent(peerId)}/payment-key`)

export const advertiseKeyToPeer = (peerId: string) =>
  post<{ message: string; peer_id: string }>(`/dm/${encodeURIComponent(peerId)}/advertise-key`)

// ─── PubSub / DHT ─────────────────────────────────────────────────────────────

export const getPubSubConfig = () => get<PubSubConfig>('/pubsub/config')
export const getDHTStatus = () => get<DHTStatus>('/dht/status')
export const getPubSubMesh = () =>
  get<{ mesh: Record<string, string[]>; total_mesh_peers: number }>('/pubsub/mesh')

// ─── Files / Bitswap ──────────────────────────────────────────────────────────

export interface DownloadRequest {
  file_cid: string
  file_name?: string
}

export interface DownloadResponse {
  message: string
  file_cid: string
  file_name: string
  // Present when the file is served directly from this node's local store
  file_size?: number
  save_path?: string
  local?: boolean
}

export const downloadFileByCID = (cid: string, name?: string) =>
  post<DownloadResponse>('/files/download', { file_cid: cid, file_name: name ?? 'download' })

export const getSharedFiles = () =>
  get<{ shared_files: Array<{ cid: string; filename: string; filesize: number; filepath: string }>; count: number }>('/files/shared')

export const unshareFile = (cid: string) => {
  const origin = API_ORIGIN ?? ''
  return fetch(`${origin}/api/v1/files/shared/${encodeURIComponent(cid)}`, { method: 'DELETE' })
    .then((r) => r.json() as Promise<ApiResponse<{ message: string; cid: string; filename: string }>>)
    .then((j) => { if (!j.success) throw new Error(j.error?.message ?? 'Unshare failed'); return j.data })
}

export interface UploadShareResponse {
  message: string
  filename: string
  size: number
  topic: string
  saved_path: string
}

/** Upload a local file and share it to a topic via Bitswap / MerkleDag. */
export async function uploadAndShareFile(
  file: File,
  topic: string,
  requirePayment?: boolean,
): Promise<UploadShareResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('topic', topic)
  if (requirePayment !== undefined) {
    form.append('require_payment', requirePayment ? 'true' : 'false')
  }
  const origin = API_ORIGIN ?? ''
  const res = await fetch(`${origin}/api/v1/files/upload`, { method: 'POST', body: form })
  const json: ApiResponse<UploadShareResponse> = await res.json()
  if (!json.success) throw new Error(json.error?.message ?? 'Upload failed')
  return json.data
}

// ─── WebSocket helpers ────────────────────────────────────────────────────────

export const WS_BASE: string = API_ORIGIN
  ? API_ORIGIN.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

export const wsMessages = () => new WebSocket(`${WS_BASE}/ws/messages`)
export const wsPeers = () => new WebSocket(`${WS_BASE}/ws/peers`)
export const wsSystem = () => new WebSocket(`${WS_BASE}/ws/system`)
export const wsDM = () => new WebSocket(`${WS_BASE}/ws/dm`)
// ─── Bitswap 1.3.0 payment API ───────────────────────────────────────────────

export interface BitswapPaymentStatus {
  payment_enabled: boolean
  protocol_version: string | null
  server_wallet: string
  network: string
  usdc_address: string
  ledger_attached: boolean
  max_auto_pay_units: number
  max_auto_pay_usdc: number
}

export interface BitswapPaymentLedger {
  payment_enabled: boolean
  // Earned (server received payments for serving blocks)
  earned_flows: number
  earned_usdc_units: number
  earned_usdc: number
  unique_payers: number
  // Spent (client sent payments to download blocks)
  spent_flows: number
  spent_usdc_units: number
  spent_usdc: number
  unique_payees: number
  // Misc
  pending_offers: number
  message?: string
}

export interface BitswapPaymentConfig {
  payment_enabled: boolean
  units_per_kb: number
  free_threshold_bytes: number
  free_threshold_kb: number
  max_auto_pay_units: number
  max_auto_pay_usdc: number
  message?: string
}

export const getBitswapPaymentStatus = () =>
  get<BitswapPaymentStatus>('/bitswap/payment/status')

export const getBitswapPaymentLedger = () =>
  get<BitswapPaymentLedger>('/bitswap/payment/ledger')

export const getBitswapPaymentConfig = () =>
  get<BitswapPaymentConfig>('/bitswap/payment/config')

export const updateBitswapPaymentConfig = (config: {
  units_per_kb?: number
  free_threshold_kb?: number
  max_auto_pay_usdc?: number
}) => {
  const origin = API_ORIGIN ?? ''
  return fetch(`${origin}/api/v1/bitswap/payment/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
    .then((r) => r.json() as Promise<ApiResponse<{ updated: Record<string, number> }>>)
    .then((j) => {
      if (!j.success) throw new Error(j.error?.message ?? 'Update failed')
      return j.data
    })
}