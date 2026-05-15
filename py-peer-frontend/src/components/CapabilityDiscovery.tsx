/**
 * CapabilityDiscovery
 *
 * Two sections:
 *  A) My Capabilities — announce new, view active, revoke, reannounce all
 *  B) Discover Peers  — search DHT for providers of a capability + connect
 */

import { useState, useEffect, useCallback } from 'react'
import {
  MagnifyingGlassIcon,
  SignalIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  MegaphoneIcon,
  XMarkIcon,
  PlusIcon,
} from '@heroicons/react/24/outline'
import * as api from '../api/client'
import Spinner from './Spinner'

// ─── Well-known capability options ───────────────────────────────────────────

const WELL_KNOWN = [
  { value: 'chat-peer/v1.0',      label: '💬 Chat Peer' },
  { value: 'goose-agent/v1.0',    label: '🪿 Goose Agent' },
  { value: 'rag-provider/v1.0',   label: '🔍 RAG Provider' },
  { value: 'bitswap-server/v1.0', label: '📦 Bitswap Server' },
  { value: 'compute-node/v1.0',   label: '⚙️  Compute Node' },
]

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProviderRow {
  peer_id: string
  addrs: string[]
  status: 'idle' | 'connecting' | 'connected' | 'error'
  error?: string
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function CapabilityDiscovery() {
  // ── Section A: My Capabilities ─────────────────────────────────────────────
  const [announced, setAnnounced] = useState<string[]>([])
  const [loadingAnnounced, setLoadingAnnounced] = useState(false)

  const [announcePreset, setAnnouncePreset] = useState(WELL_KNOWN[0].value)
  const [announceCustom, setAnnounceCustom] = useState('')
  const [useAnnounceCustom, setUseAnnounceCustom] = useState(false)
  const [announcing, setAnnouncing] = useState(false)
  const [announceMsg, setAnnounceMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const [revoking, setRevoking] = useState<string | null>(null)

  const [reannouncing, setReannouncing] = useState(false)
  const [reannounceMsg, setReannounceMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // ── Section B: Discover Peers ──────────────────────────────────────────────
  const [discoverPreset, setDiscoverPreset] = useState(WELL_KNOWN[0].value)
  const [discoverCustom, setDiscoverCustom] = useState('')
  const [useDiscoverCustom, setUseDiscoverCustom] = useState(false)
  const [searching, setSearching] = useState(false)
  const [searchErr, setSearchErr] = useState('')
  const [providers, setProviders] = useState<ProviderRow[] | null>(null)

  const effectiveAnnounceCap = useAnnounceCustom ? announceCustom.trim() : announcePreset
  const effectiveDiscoverCap = useDiscoverCustom ? discoverCustom.trim() : discoverPreset

  // ── Load current announced capabilities ────────────────────────────────────

  const refreshAnnounced = useCallback(async () => {
    setLoadingAnnounced(true)
    try {
      const res = await api.getCapabilities()
      setAnnounced(res.announced)
    } catch {
      // silently ignore
    } finally {
      setLoadingAnnounced(false)
    }
  }, [])

  useEffect(() => { refreshAnnounced() }, [refreshAnnounced])

  // ── Announce ───────────────────────────────────────────────────────────────

  const handleAnnounce = async () => {
    if (!effectiveAnnounceCap) return
    setAnnouncing(true)
    setAnnounceMsg(null)
    try {
      await api.announceCapability(effectiveAnnounceCap)
      setAnnounceMsg({ ok: true, text: `Announced!` })
      await refreshAnnounced()
    } catch (e: unknown) {
      setAnnounceMsg({ ok: false, text: e instanceof Error ? e.message : 'Announce failed' })
    } finally {
      setAnnouncing(false)
      setTimeout(() => setAnnounceMsg(null), 3000)
    }
  }

  // ── Revoke ─────────────────────────────────────────────────────────────────

  const handleRevoke = async (cap: string) => {
    setRevoking(cap)
    try {
      await api.revokeCapability(cap)
      await refreshAnnounced()
    } catch {
      // silently ignore
    } finally {
      setRevoking(null)
    }
  }

  // ── Reannounce all ─────────────────────────────────────────────────────────

  const handleReannounce = async () => {
    setReannouncing(true)
    setReannounceMsg(null)
    try {
      const res = await api.reannounceCapabilities()
      setReannounceMsg({ ok: true, text: res.message })
    } catch (e: unknown) {
      setReannounceMsg({ ok: false, text: e instanceof Error ? e.message : 'Reannounce failed' })
    } finally {
      setReannouncing(false)
      setTimeout(() => setReannounceMsg(null), 4000)
    }
  }

  // ── Search DHT ─────────────────────────────────────────────────────────────

  const handleSearch = async () => {
    if (!effectiveDiscoverCap) return
    setSearching(true)
    setSearchErr('')
    setProviders(null)
    try {
      const result = await api.findCapabilityProviders(effectiveDiscoverCap, 20)
      setProviders(result.providers.map((p) => ({ ...p, status: 'idle' as const })))
    } catch (e: unknown) {
      setSearchErr(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  // ── Connect to provider ────────────────────────────────────────────────────

  const handleConnect = async (index: number) => {
    const row = providers![index]
    const addr =
      row.addrs.find((a) => a.includes('/tcp/') && a.includes('/ip4/')) ?? row.addrs[0]

    if (!addr) {
      setProviders((prev) => {
        if (!prev) return prev
        const next = [...prev]
        next[index] = { ...next[index], status: 'error', error: 'No usable address' }
        return next
      })
      return
    }

    setProviders((prev) => {
      if (!prev) return prev
      const next = [...prev]
      next[index] = { ...next[index], status: 'connecting', error: undefined }
      return next
    })

    try {
      await api.connectToPeer(addr)
      setProviders((prev) => {
        if (!prev) return prev
        const next = [...prev]
        next[index] = { ...next[index], status: 'connected' }
        return next
      })
    } catch (e: unknown) {
      setProviders((prev) => {
        if (!prev) return prev
        const next = [...prev]
        next[index] = {
          ...next[index],
          status: 'error',
          error: e instanceof Error ? e.message : 'Connection failed',
        }
        return next
      })
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">

      {/* ── Section A: My Capabilities ──────────────────────────────────── */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          My Capabilities
        </h3>

        {/* Active capabilities list */}
        <div className="min-h-[28px]">
          {loadingAnnounced ? (
            <Spinner className="h-4 w-4 text-indigo-400" />
          ) : announced.length === 0 ? (
            <p className="text-xs text-gray-400 italic">No capabilities announced yet.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {announced.map((cap) => (
                <span
                  key={cap}
                  className="flex items-center gap-1 rounded-full bg-indigo-50 border border-indigo-200 pl-2.5 pr-1 py-0.5 text-xs font-medium text-indigo-700"
                >
                  {cap}
                  <button
                    type="button"
                    onClick={() => handleRevoke(cap)}
                    disabled={revoking === cap}
                    className="rounded-full p-0.5 hover:bg-indigo-200 disabled:opacity-50 transition"
                    title="Revoke"
                  >
                    {revoking === cap
                      ? <ArrowPathIcon className="h-3 w-3 animate-spin" />
                      : <XMarkIcon className="h-3 w-3" />
                    }
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Announce new capability */}
        <div className="space-y-2">
          {!useAnnounceCustom ? (
            <select
              value={announcePreset}
              onChange={(e) => setAnnouncePreset(e.target.value)}
              className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              {WELL_KNOWN.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={announceCustom}
              onChange={(e) => setAnnounceCustom(e.target.value)}
              placeholder="my-capability/v1.0"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          )}
          <button
            type="button"
            onClick={() => setUseAnnounceCustom((v) => !v)}
            className="text-xs text-indigo-500 hover:text-indigo-700 transition"
          >
            {useAnnounceCustom ? '← Use preset' : '+ Custom key'}
          </button>
        </div>

        {/* Announce + Reannounce buttons */}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={announcing || !effectiveAnnounceCap}
            onClick={handleAnnounce}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {announcing
              ? <><Spinner className="h-4 w-4 text-white" /> Announcing…</>
              : <><PlusIcon className="h-4 w-4" /> Announce</>
            }
          </button>
          <button
            type="button"
            disabled={reannouncing || announced.length === 0}
            onClick={handleReannounce}
            className="flex items-center gap-1.5 rounded-md border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed transition"
            title="Re-broadcast all active capabilities to the DHT"
          >
            {reannouncing
              ? <Spinner className="h-4 w-4 text-indigo-600" />
              : <MegaphoneIcon className="h-4 w-4" />
            }
            Reannounce
          </button>
        </div>

        {/* Feedback messages */}
        {announceMsg && (
          <p className={`text-xs ${announceMsg.ok ? 'text-emerald-600' : 'text-red-500'}`}>
            {announceMsg.ok ? '✓' : '✗'} {announceMsg.text}
          </p>
        )}
        {reannounceMsg && (
          <p className={`text-xs ${reannounceMsg.ok ? 'text-emerald-600' : 'text-red-500'}`}>
            {reannounceMsg.ok ? '✓' : '✗'} {reannounceMsg.text}
          </p>
        )}
      </div>

      {/* Divider */}
      <div className="border-t border-gray-200" />

      {/* ── Section B: Discover Peers ────────────────────────────────────── */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Find Peers by Capability
        </h3>

        <div className="space-y-2">
          {!useDiscoverCustom ? (
            <select
              value={discoverPreset}
              onChange={(e) => { setDiscoverPreset(e.target.value); setProviders(null) }}
              className="block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              {WELL_KNOWN.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={discoverCustom}
              onChange={(e) => { setDiscoverCustom(e.target.value); setProviders(null) }}
              placeholder="my-capability/v1.0"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          )}
          <button
            type="button"
            onClick={() => { setUseDiscoverCustom((v) => !v); setProviders(null); setSearchErr('') }}
            className="text-xs text-indigo-500 hover:text-indigo-700 transition"
          >
            {useDiscoverCustom ? '← Use preset' : '+ Custom key'}
          </button>
        </div>

        <button
          type="button"
          disabled={searching || !effectiveDiscoverCap}
          onClick={handleSearch}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {searching
            ? <><Spinner className="h-4 w-4 text-white" /> Searching DHT…</>
            : <><MagnifyingGlassIcon className="h-4 w-4" /> Find Providers</>
          }
        </button>

        {searchErr && (
          <p className="flex items-center gap-1 text-xs text-red-500">
            <ExclamationCircleIcon className="h-4 w-4 shrink-0" />
            {searchErr}
          </p>
        )}

        {providers !== null && (
          <div className="space-y-1">
            <p className="text-xs text-gray-400 font-medium">
              {providers.length === 0
                ? 'No providers found for this capability.'
                : `${providers.length} provider${providers.length !== 1 ? 's' : ''} found`}
            </p>
            {providers.map((row, i) => (
              <ProviderRowItem
                key={row.peer_id}
                row={row}
                onConnect={() => handleConnect(i)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── ProviderRowItem sub-component ───────────────────────────────────────────

function ProviderRowItem({
  row,
  onConnect,
}: {
  row: ProviderRow
  onConnect: () => void
}) {
  const short = row.peer_id.length > 20
    ? `${row.peer_id.slice(0, 8)}…${row.peer_id.slice(-6)}`
    : row.peer_id

  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-xs text-gray-700" title={row.peer_id}>
          {short}
        </p>
        {row.addrs.length > 0 && (
          <p className="truncate text-[10px] text-gray-400" title={row.addrs[0]}>
            {row.addrs[0]}
          </p>
        )}
        {row.status === 'error' && row.error && (
          <p className="text-[10px] text-red-500">{row.error}</p>
        )}
      </div>

      {row.status === 'idle' && (
        <button
          onClick={onConnect}
          className="shrink-0 flex items-center gap-1 rounded-md bg-white border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-indigo-50 hover:border-indigo-400 hover:text-indigo-700 transition"
        >
          <SignalIcon className="h-3.5 w-3.5" /> Connect
        </button>
      )}
      {row.status === 'connecting' && (
        <span className="shrink-0 flex items-center gap-1 text-xs text-indigo-500">
          <ArrowPathIcon className="h-3.5 w-3.5 animate-spin" /> Connecting…
        </span>
      )}
      {row.status === 'connected' && (
        <span className="shrink-0 flex items-center gap-1 text-xs text-emerald-600 font-medium">
          <CheckCircleIcon className="h-3.5 w-3.5" /> Connected
        </span>
      )}
      {row.status === 'error' && (
        <button
          onClick={onConnect}
          className="shrink-0 flex items-center gap-1 rounded-md bg-white border border-red-300 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 transition"
        >
          <ArrowPathIcon className="h-3.5 w-3.5" /> Retry
        </button>
      )}
    </div>
  )
}

