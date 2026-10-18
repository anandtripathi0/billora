import type {ConfigContext, ExpoConfig} from 'expo/config';

export default ({config}: ConfigContext): ExpoConfig => {
  if (process.env.EAS_BUILD === 'true') {
    const value = process.env.EXPO_PUBLIC_API_BASE_URL;
    if (!value || !value.startsWith('https://')) throw new Error('Set EXPO_PUBLIC_API_BASE_URL to the confirmed public HTTPS Django origin in the EAS build environment.');
    const url = new URL(value);
    if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('API URL must be an HTTPS origin without credentials or paths.');
  }
  return {...config, name:'Billora',slug:'billora'} as ExpoConfig;
};
