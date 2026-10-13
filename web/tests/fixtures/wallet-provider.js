// Browser-only fake wallet for tests. No keys and no real transaction signing.
(() => {
  const listeners = {};
  const state = { chain: '0xa', account: '0x1111111111111111111111111111111111111111', reject: false, requests: [] };
  window.__wallet = state;
  const provider = {
    request: async ({ method, params }) => {
      state.requests.push({ method, params });
      if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [state.account];
      if (method === 'eth_chainId') return state.chain;
      if (method === 'wallet_switchEthereumChain') {
        state.chain = params[0].chainId;
        listeners.chainChanged?.forEach(fn => fn(state.chain));
        return null;
      }
      if (method === 'eth_sendTransaction') {
        if (state.reject) throw Object.assign(new Error('User rejected the request'), { code: 4001 });
        return `0x${'ab'.repeat(32)}`;
      }
      throw new Error(`Unexpected wallet method ${method}`);
    },
    on: (name, handler) => { (listeners[name] ??= []).push(handler); },
    removeListener: (name, handler) => { listeners[name] = listeners[name]?.filter(fn => fn !== handler); },
  };
  window.ethereum = provider;
  window.__emitWallet = (name, value) => { listeners[name]?.forEach(fn => fn(value)); };
  window.addEventListener('eip6963:requestProvider', () => window.dispatchEvent(new CustomEvent('eip6963:announceProvider', {
    detail: { info: { uuid: 'test-provider', name: 'Test wallet' }, provider },
  })));
})();
