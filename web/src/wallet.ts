import { useEffect, useState } from "react";
import type { Address, EIP1193Provider } from "viem";
import { getAddress, isAddress } from "viem";

export type Provider = EIP1193Provider & {
  on?: (event: string, listener: (...args: unknown[]) => void) => void;
  removeListener?: (
    event: string,
    listener: (...args: unknown[]) => void,
  ) => void;
};
export type WalletOption = { id: string; name: string; provider: Provider };
declare global {
  interface Window {
    ethereum?: Provider;
  }
}

export function useWallet() {
  const [options, setOptions] = useState<WalletOption[]>([]);
  const [selected, setSelected] = useState<WalletOption | null>(null);
  const [account, setAccount] = useState<Address | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  useEffect(() => {
    const announce = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          info: { uuid: string; name: string };
          provider: Provider;
        }>
      ).detail;
      if (!detail?.provider?.request || !detail.info?.uuid) return;
      setOptions((current) => [
        ...current.filter(
          (item) =>
            item.provider !== detail.provider &&
            item.id !== detail.info.uuid &&
            item.id !== "injected",
        ),
        {
          id: detail.info.uuid,
          name: detail.info.name,
          provider: detail.provider,
        },
      ]);
    };
    window.addEventListener("eip6963:announceProvider", announce);
    if (window.ethereum)
      setOptions([
        { id: "injected", name: "Browser wallet", provider: window.ethereum },
      ]);
    window.dispatchEvent(new Event("eip6963:requestProvider"));
    return () =>
      window.removeEventListener("eip6963:announceProvider", announce);
  }, []);
  useEffect(() => {
    if (!selected) return;
    const provider = selected.provider;
    const accountsChanged = (...args: unknown[]) => {
      const accounts = args[0] as string[];
      setAccount(
        accounts?.[0] && isAddress(accounts[0])
          ? getAddress(accounts[0])
          : null,
      );
    };
    const chainChanged = (...args: unknown[]) => setChainId(Number(args[0]));
    const disconnected = () => {
      setAccount(null);
      setChainId(null);
    };
    provider.on?.("accountsChanged", accountsChanged);
    provider.on?.("chainChanged", chainChanged);
    provider.on?.("disconnect", disconnected);
    let active = true;
    provider
      .request({ method: "eth_chainId" })
      .then((id) => {
        if (active) setChainId(Number(id));
      })
      .catch(() => {
        if (active) setChainId(null);
      });
    return () => {
      active = false;
      provider.removeListener?.("accountsChanged", accountsChanged);
      provider.removeListener?.("chainChanged", chainChanged);
      provider.removeListener?.("disconnect", disconnected);
    };
  }, [selected]);
  return {
    options,
    selected,
    setSelected,
    account,
    setAccount,
    chainId,
    setChainId,
    disconnect: () => {
      setSelected(null);
      setAccount(null);
      setChainId(null);
    },
  };
}
