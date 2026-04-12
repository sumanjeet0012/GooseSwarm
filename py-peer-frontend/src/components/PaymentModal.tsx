import { useState, useCallback } from 'react'
import { XMarkIcon, CurrencyDollarIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/solid'
import Blockies from 'react-18-blockies'
import { usePyPeer } from '../context/PyPeerContext'

// ─── Minimal MetaMask / EIP-1193 types ───────────────────────────────────────

declare global {
  interface Window {
    ethereum?: {
      isMetaMask?: boolean
      request: (args: { method: string; params?: unknown[] }) => Promise<unknown>
      on: (event: string, handler: (...args: unknown[]) => void) => void
    }
  }
}

interface PaymentModalProps {
  peerId: string
  recipientAddress: string
  onClose: () => void
}

type TxState = 'idle' | 'connecting' | 'awaiting' | 'pending' | 'success' | 'error'

const PRESET_AMOUNTS = ['0.001', '0.005', '0.01', '0.05', '0.1']

// Convert ETH amount string → hex wei
function ethToHex(eth: string): string {
  const wei = BigInt(Math.round(parseFloat(eth) * 1e18))
  return '0x' + wei.toString(16)
}

function shortAddr(addr: string) {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

function shortId(id: string) {
  return `${id.slice(0, 6)}…${id.slice(-4)}`
}

// Network Configs
interface NetworkConfig {
  id: string
  name: string
  chainId: string
  currency: string
  rpcUrl?: string
  explorerUrl: string
}

const NETWORKS: Record<string, NetworkConfig> = {
  mainnet: {
    id: 'mainnet',
    name: 'Ethereum Mainnet',
    chainId: '0x1', // 1
    currency: 'ETH',
    explorerUrl: 'https://etherscan.io',
  },
  sepolia: {
    id: 'sepolia',
    name: 'Sepolia Testnet',
    chainId: '0xaa36a7', // 11155111
    currency: 'SEP',
    rpcUrl: 'https://sepolia.infura.io/v3/',
    explorerUrl: 'https://sepolia.etherscan.io',
  },
  base: {
    id: 'base',
    name: 'Base Mainnet',
    chainId: '0x2105', // 8453
    currency: 'ETH',
    rpcUrl: 'https://mainnet.base.org',
    explorerUrl: 'https://basescan.org',
  }
}

export default function PaymentModal({ peerId, recipientAddress, onClose }: PaymentModalProps) {
  const [amount, setAmount] = useState('0.01')
  const [selectedNetworkId, setSelectedNetworkId] = useState<string>('sepolia')
  const [txState, setTxState] = useState<TxState>('idle')
  const [txHash, setTxHash] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const [connectedAccount, setConnectedAccount] = useState('')

  const { sendDM } = usePyPeer()

  const network = NETWORKS[selectedNetworkId]

  const hasMetaMask = typeof window !== 'undefined' && !!window.ethereum?.isMetaMask

  const connectWallet = useCallback(async (): Promise<string> => {
    if (!window.ethereum) throw new Error('MetaMask not found')
    
    // Switch to selected network
    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: network.chainId }],
      })
    } catch (switchError: any) {
      if (switchError.code === 4902 && network.rpcUrl) {
        try {
          await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [
              {
                chainId: network.chainId,
                chainName: network.name,
                nativeCurrency: {
                  name: network.currency,
                  symbol: network.currency,
                  decimals: 18,
                },
                rpcUrls: [network.rpcUrl],
                blockExplorerUrls: [network.explorerUrl],
              },
            ],
          })
        } catch (addError) {
          throw new Error(`Failed to add ${network.name} to MetaMask`)
        }
      } else {
        throw new Error(`Failed to switch to ${network.name}`)
      }
    }

    const accounts = (await window.ethereum.request({ method: 'eth_requestAccounts' })) as string[]
    if (!accounts || accounts.length === 0) throw new Error('No accounts returned')
    setConnectedAccount(accounts[0])
    return accounts[0]
  }, [network])

  const sendPayment = useCallback(async () => {
    if (!hasMetaMask) {
      setErrorMsg('MetaMask is not installed. Please install it from metamask.io')
      setTxState('error')
      return
    }

    const parsedAmount = parseFloat(amount)
    if (isNaN(parsedAmount) || parsedAmount <= 0) {
      setErrorMsg('Please enter a valid amount')
      setTxState('error')
      return
    }

    try {
      setTxState('connecting')
      setErrorMsg('')

      const from = connectedAccount || await connectWallet()

      setTxState('awaiting')

      const txHash = await window.ethereum!.request({
        method: 'eth_sendTransaction',
        params: [{
          from,
          to: recipientAddress,
          value: ethToHex(amount),
          // gas is auto-estimated by MetaMask
        }],
      }) as string

      setTxHash(txHash)
      setTxState('pending')

      // Poll for receipt
      pollReceipt(txHash)

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      // User rejected
      if (msg.includes('rejected') || msg.includes('denied') || msg.includes('4001')) {
        setTxState('idle')
        return
      }
      setErrorMsg(msg)
      setTxState('error')
    }
  }, [hasMetaMask, amount, connectedAccount, connectWallet, recipientAddress])

  const pollReceipt = useCallback(async (hash: string) => {
    if (!window.ethereum) return
    let attempts = 0
    const check = async () => {
      try {
        const receipt = await window.ethereum!.request({
          method: 'eth_getTransactionReceipt',
          params: [hash],
        })
        if (receipt) {
          setTxState('success')
          const msg = `💳 Payment of ${amount} ${network.currency} sent via ${network.name}.\n${network.explorerUrl}/tx/${hash}`
          sendDM(peerId, msg).catch(() => {})
          return
        }
      } catch { /* ignore */ }
      attempts++
      if (attempts < 60) setTimeout(check, 3000)
    }
    setTimeout(check, 3000)
  }, [amount, network, peerId, sendDM])

  const etherscanUrl = txHash
    ? `${network.explorerUrl}/tx/${txHash}`
    : ''

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

          {/* Network Selection */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-2">Select Network</label>
            <select
              value={selectedNetworkId}
              onChange={(e) => setSelectedNetworkId(e.target.value)}
              className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
            >
              {Object.values(NETWORKS).map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </div>

          {/* Amount presets */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-2">Amount ({network.currency})</label>
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

          {/* Connected wallet */}
          {connectedAccount && (
            <p className="text-xs text-gray-500">
              From: <span className="font-mono">{shortAddr(connectedAccount)}</span> ({network.name})
            </p>
          )}

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
                    href={etherscanUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline break-all"
                  >
                    View on {network.name === 'Base Mainnet' ? 'Basescan' : 'Etherscan'}
                  </a>
                )}
              </div>
            </div>
          )}

          {txState === 'pending' && (
            <div className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-700">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              <span>Transaction submitted — waiting for confirmation…</span>
            </div>
          )}

          {!hasMetaMask && (
            <div className="flex items-start gap-2 rounded-xl bg-orange-50 px-3 py-2.5 text-xs text-orange-700">
              <ExclamationTriangleIcon className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>
                MetaMask not detected.{' '}
                <a href="https://metamask.io" target="_blank" rel="noopener noreferrer" className="underline font-semibold">
                  Install MetaMask
                </a>{' '}
                to send payments.
              </span>
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
              disabled={!hasMetaMask || txState === 'connecting' || txState === 'awaiting' || txState === 'pending'}
              className="flex-1 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40 transition"
            >
              {txState === 'connecting' ? 'Connecting…'
                : txState === 'awaiting' ? 'Confirm in MetaMask…'
                : txState === 'pending' ? 'Pending…'
                : `Send ${amount} ETH`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
