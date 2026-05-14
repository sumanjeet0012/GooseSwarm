import { useCallback, useEffect, useState } from 'react'
import {
  XMarkIcon,
  CurrencyDollarIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
  PencilSquareIcon,
} from '@heroicons/react/24/outline'
import {
  getBitswapPaymentStatus,
  getBitswapPaymentLedger,
  getBitswapPaymentConfig,
  updateBitswapPaymentConfig,
  type BitswapPaymentStatus,
  type BitswapPaymentLedger,
  type BitswapPaymentConfig,
} from '../api/client'

interface BitswapPaymentPanelProps {
  isOpen: boolean
  onClose: () => void
}

function shortAddr(addr: string) {
  if (!addr) return '—'
  return `${addr.slice(0, 8)}…${addr.slice(-6)}`
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: string
}) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${accent ?? 'text-gray-900'}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

export default function BitswapPaymentPanel({ isOpen, onClose }: BitswapPaymentPanelProps) {
  const [status, setStatus] = useState<BitswapPaymentStatus | null>(null)
  const [ledger, setLedger] = useState<BitswapPaymentLedger | null>(null)
  const [config, setConfig] = useState<BitswapPaymentConfig | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Config edit state
  const [editing, setEditing] = useState(false)
  const [editUnitsPerKb, setEditUnitsPerKb] = useState('')
  const [editFreeThresholdKb, setEditFreeThresholdKb] = useState('')
  const [editMaxAutoPay, setEditMaxAutoPay] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [s, l, c] = await Promise.all([
        getBitswapPaymentStatus(),
        getBitswapPaymentLedger(),
        getBitswapPaymentConfig(),
      ])
      setStatus(s)
      setLedger(l)
      setConfig(c)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load payment info')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen) refresh()
  }, [isOpen, refresh])

  const startEdit = () => {
    if (!config) return
    setEditUnitsPerKb(String(config.units_per_kb))
    setEditFreeThresholdKb(String(config.free_threshold_kb))
    setEditMaxAutoPay(String(config.max_auto_pay_usdc))
    setSaveMsg('')
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setSaveMsg('')
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveMsg('')
    try {
      await updateBitswapPaymentConfig({
        units_per_kb: Number(editUnitsPerKb),
        free_threshold_kb: Number(editFreeThresholdKb),
        max_auto_pay_usdc: Number(editMaxAutoPay),
      })
      setSaveMsg('✅ Config updated')
      setEditing(false)
      await refresh()
    } catch (e: unknown) {
      setSaveMsg(`❌ ${e instanceof Error ? e.message : 'Save failed'}`)
    } finally {
      setSaving(false)
    }
  }

  if (!isOpen) return null

  const paymentEnabled = status?.payment_enabled ?? false

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="relative w-full max-w-lg rounded-xl bg-white shadow-2xl ring-1 ring-gray-200 mx-4 flex flex-col max-h-[90vh]">

        {/* ── Header ── */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 flex-shrink-0">
          <div className="flex items-center gap-2">
            <CurrencyDollarIcon className="h-5 w-5 text-violet-600" />
            <h2 className="text-base font-semibold text-gray-900">Bitswap 1.3.0 Payments</h2>
            {paymentEnabled ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                <CheckCircleIcon className="h-3.5 w-3.5" /> Active
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
                Disabled
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={refresh}
              disabled={loading}
              className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition disabled:opacity-40"
              title="Refresh"
            >
              <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
            >
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* ── Body (scrollable) ── */}
        <div className="overflow-y-auto flex-1 px-5 py-5 space-y-5">

          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              <ExclamationTriangleIcon className="h-4 w-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {/* ── Disabled notice ── */}
          {!paymentEnabled && !loading && (
            <div className="flex items-start gap-3 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
              <InformationCircleIcon className="h-5 w-5 flex-shrink-0 mt-0.5 text-amber-500" />
              <div>
                <p className="font-medium">Payment mode is disabled.</p>
                <p className="mt-1 text-xs text-amber-700">
                  Add these to your <code className="font-mono bg-amber-100 px-1 rounded">.env</code> file and restart:
                </p>
                <pre className="mt-2 rounded bg-amber-100 px-3 py-2 text-xs font-mono whitespace-pre-wrap">
{`BITSWAP_PAYMENT_ENABLED=true
AGENT_PRIVATE_KEY=0x<your_wallet_key>
BITSWAP_NETWORK=base-sepolia`}
                </pre>
              </div>
            </div>
          )}

          {/* ── Wallet & network info ── */}
          {paymentEnabled && status && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                Server Wallet
              </h3>
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-500">Address</span>
                  <span
                    className="font-mono text-gray-800 cursor-pointer hover:text-violet-600 transition"
                    title={status.server_wallet}
                    onClick={() => navigator.clipboard?.writeText(status.server_wallet)}
                  >
                    {shortAddr(status.server_wallet)}
                    <span className="ml-1 text-xs text-gray-400">(click to copy)</span>
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-500">Network</span>
                  <span className="font-medium text-gray-800">{status.network}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-500">USDC contract</span>
                  <span
                    className="font-mono text-xs text-gray-600 cursor-pointer hover:text-violet-600 transition"
                    title={status.usdc_address}
                    onClick={() => navigator.clipboard?.writeText(status.usdc_address)}
                  >
                    {shortAddr(status.usdc_address)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-500">Protocol</span>
                  <span className="font-mono text-xs text-violet-700 bg-violet-50 px-2 py-0.5 rounded">
                    {status.protocol_version}
                  </span>
                </div>
              </div>
            </section>
          )}

          {/* ── Ledger stats ── */}
          {paymentEnabled && ledger && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                Payment Statistics
              </h3>

              {/* Earned row */}
              <p className="text-xs font-medium text-gray-500 mb-1.5 flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-green-500"></span>
                Earned — blocks served to peers
              </p>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <StatCard
                  label="USDC Earned"
                  value={`$${(ledger.earned_usdc ?? 0).toFixed(6)}`}
                  sub={`${ledger.earned_usdc_units ?? 0} micro-units`}
                  accent="text-green-700"
                />
                <StatCard
                  label="Earning Flows"
                  value={ledger.earned_flows ?? 0}
                  sub={`from ${ledger.unique_payers ?? 0} peer(s)`}
                  accent="text-green-600"
                />
              </div>

              {/* Spent row */}
              <p className="text-xs font-medium text-gray-500 mb-1.5 flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-violet-500"></span>
                Spent — blocks downloaded from peers
              </p>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <StatCard
                  label="USDC Spent"
                  value={`$${(ledger.spent_usdc ?? 0).toFixed(6)}`}
                  sub={`${ledger.spent_usdc_units ?? 0} micro-units`}
                  accent="text-violet-700"
                />
                <StatCard
                  label="Spending Flows"
                  value={ledger.spent_flows ?? 0}
                  sub={`to ${ledger.unique_payees ?? 0} peer(s)`}
                  accent="text-violet-600"
                />
              </div>

              {/* Net balance */}
              {(() => {
                const net = (ledger.earned_usdc ?? 0) - (ledger.spent_usdc ?? 0)
                return (
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard
                      label="Net Balance"
                      value={`${net >= 0 ? '+' : ''}$${net.toFixed(6)}`}
                      sub="earned minus spent"
                      accent={net >= 0 ? 'text-green-700' : 'text-red-600'}
                    />
                    <StatCard
                      label="Pending Offers"
                      value={ledger.pending_offers ?? 0}
                      sub="awaiting authorization"
                      accent={(ledger.pending_offers ?? 0) > 0 ? 'text-amber-600' : undefined}
                    />
                  </div>
                )
              })()}
            </section>
          )}

          {/* ── Pricing config ── */}
          {paymentEnabled && config && (
            <section>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Pricing Config
                </h3>
                {!editing && (
                  <button
                    onClick={startEdit}
                    className="flex items-center gap-1 text-xs text-violet-600 hover:text-violet-800 transition"
                  >
                    <PencilSquareIcon className="h-3.5 w-3.5" />
                    Edit
                  </button>
                )}
              </div>

              {!editing ? (
                <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Price per KB</span>
                    <span className="font-medium text-gray-800">{config.units_per_kb} units/KB</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Free threshold</span>
                    <span className="font-medium text-gray-800">≤ {config.free_threshold_kb} KB</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Max auto-pay</span>
                    <span className="font-medium text-gray-800">
                      ${config.max_auto_pay_usdc.toFixed(6)} USDC
                      <span className="text-gray-400 text-xs ml-1">({config.max_auto_pay_units} units)</span>
                    </span>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSave} className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-4 space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Price per KB (units)
                    </label>
                    <input
                      type="number"
                      min="0"
                      value={editUnitsPerKb}
                      onChange={(e) => setEditUnitsPerKb(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-900 shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      required
                    />
                    <p className="mt-0.5 text-xs text-gray-400">1 unit = $0.000001 USDC. Default: 10</p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Free threshold (KB)
                    </label>
                    <input
                      type="number"
                      min="0"
                      value={editFreeThresholdKb}
                      onChange={(e) => setEditFreeThresholdKb(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-900 shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      required
                    />
                    <p className="mt-0.5 text-xs text-gray-400">Blocks ≤ this size are served free. Default: 4</p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Max auto-pay (USDC)
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="0.000001"
                      value={editMaxAutoPay}
                      onChange={(e) => setEditMaxAutoPay(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-900 shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      required
                    />
                    <p className="mt-0.5 text-xs text-gray-400">Client won't auto-pay above this amount. Default: 0.001</p>
                  </div>
                  {saveMsg && (
                    <p className={`text-xs font-medium ${saveMsg.startsWith('✅') ? 'text-green-700' : 'text-red-600'}`}>
                      {saveMsg}
                    </p>
                  )}
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={saving}
                      className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50 transition"
                    >
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </form>
              )}
              {saveMsg && !editing && (
                <p className="mt-1 text-xs font-medium text-green-700">{saveMsg}</p>
              )}
            </section>
          )}

        </div>

        {/* ── Footer ── */}
        <div className="border-t border-gray-100 px-5 py-3 flex-shrink-0 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
