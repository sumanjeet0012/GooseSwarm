import { useState, useCallback } from 'react'
import { XMarkIcon, CurrencyDollarIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/solid'
import Blockies from 'react-18-blockies'
import * as api from '../api/client'

interface PaymentModalProps {
  peerId: string
  recipientAddress: string
  onClose: () => void
}

type TxState = 'idle' | 'sending' | 'success' | 'error'

const PRESET_AMOUNTS = ['0.001', '0.005', '0.01', '0.05', '0.1']

function shortAddr(addr: string) {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

function shortId(id: string) {
  return `${id.slice(0, 6)}…${id.slice(-4)}`
}

export default function PaymentModal({ peerId, recipientAddress, onClose }: PaymentModalProps) {
  const [amount, setAmount] = useState('0.01')
  const [txState, setTxState] = useState<TxState>('idle')
  const [txHash, setTxHash] = useState('')
  const [explorerUrl, setExplorerUrl] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  const sendPayment = useCallback(async () => {
    const parsedAmount = parseFloat(amount)
    if (isNaN(parsedAmount) || parsedAmount <= 0) {
      setErrorMsg('Please enter a valid amount')
      setTxState('error')
      return
    }

    try {
      setTxState('sending')
      setErrorMsg('')

      const result = await api.sendPaymentToPeer(peerId, parsedAmount)

      setTxHash(result.tx_hash)
      setExplorerUrl(result.explorer_url)
      setTxState('success')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setErrorMsg(msg)
      setTxState('error')
    }
  }, [amount, peerId])

  const isBusy = txState === 'sending'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-sm rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <CurrencyDollarIcon className="h-5 w-5 text-emerald-600" />
            <h2 className="text-base font-semibold text-gray-900">Send Payment</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 transition"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Recipient */}
          <div className="flex items-center gap-3 rounded-xl bg-gray-50 px-4 py-3">
            <Blockies seed={peerId} size={8} scale={4} className="rounded-full flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-gray-500">Recipient peer</p>
              <p className="text-xs font-mono text-gray-700 truncate">{shortId(peerId)}</p>
              <p className="text-xs font-mono text-emerald-700 font-semibold">{shortAddr(recipientAddress)}</p>
            </div>
          </div>

          {/* Network badge */}
          <div className="flex items-center gap-2 rounded-xl bg-indigo-50 px-4 py-2.5">
            <span className="h-2 w-2 rounded-full bg-indigo-400" />
            <span className="text-xs text-indigo-700 font-medium">Sepolia Testnet</span>
            <span className="ml-auto text-xs text-indigo-500">signed with node key</span>
          </div>

          {/* Amount presets */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-2">Amount (SEP)</label>
            <div className="flex gap-1.5 mb-2 flex-wrap">
              {PRESET_AMOUNTS.map((a) => (
                <button
                  key={a}
                  onClick={() => setAmount(a)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                    amount === a
                      ? 'bg-indigo-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
            <input
              type="number"
              min="0"
              step="0.001"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="0.01"
            />
          </div>

          {/* Status messages */}
          {txState === 'error' && (
            <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-xs text-red-700">
              <ExclamationTriangleIcon className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {txState === 'success' && (
            <div className="flex items-start gap-2 rounded-xl bg-emerald-50 px-3 py-2.5 text-xs text-emerald-700">
              <CheckCircleIcon className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Payment confirmed! 🎉</p>
                {txHash && (
                  <a
                    href={explorerUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline break-all"
                  >
                    View on Etherscan
                  </a>
                )}
              </div>
            </div>
          )}

          {txState === 'sending' && (
            <div className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-700">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              <span>Broadcasting transaction…</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-5 py-4 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 rounded-xl border border-gray-200 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition"
          >
            Cancel
          </button>
          {txState === 'success' ? (
            <button
              onClick={onClose}
              className="flex-1 rounded-xl bg-emerald-600 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 transition"
            >
              Done
            </button>
          ) : (
            <button
              onClick={sendPayment}
              disabled={isBusy}
              className="flex-1 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40 transition"
            >
              {isBusy ? 'Sending…' : `Send ${amount} SEP`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
