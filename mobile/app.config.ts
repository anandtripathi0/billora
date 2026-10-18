import type {ConfigContext, ExpoConfig} from 'expo/config';

export default ({config}: ConfigContext): ExpoConfig => {
  if (process.env.EAS_BUILD === 'true' || process.env.BILLORA_APK_BUILD === 'true') {
    const value = process.env.EXPO_PUBLIC_API_BASE_URL;
    if (!value || !value.startsWith('https://')) throw new Error('Set BILLORA_API_URL in GitHub repository variables, or EXPO_PUBLIC_API_BASE_URL in EAS, to the confirmed public HTTPS Django origin.');
    const url = new URL(value);
    if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('API URL must be an HTTPS origin without credentials or paths.');
  }
  return {...config, name:'Billora',slug:'billora'} as ExpoConfig;
};
