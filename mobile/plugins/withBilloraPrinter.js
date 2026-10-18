const {withAndroidManifest, withMainApplication, withDangerousMod} = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');
module.exports = function withBilloraPrinter(config) {
  config = withAndroidManifest(config, cfg => {
    const manifest = cfg.modResults.manifest;
    manifest['uses-permission'] = manifest['uses-permission'] || [];
    for (const [name, max] of [['android.permission.BLUETOOTH','30'],['android.permission.BLUETOOTH_ADMIN','30'],['android.permission.BLUETOOTH_CONNECT',null]]) {
      if (!manifest['uses-permission'].some(p => p.$['android:name'] === name)) manifest['uses-permission'].push({$: {'android:name':name,...(max?{'android:maxSdkVersion':max}:{})}});
    }
    manifest['uses-feature'] = manifest['uses-feature'] || [];
    if (!manifest['uses-feature'].some(f => f.$['android:name'] === 'android.hardware.usb.host')) manifest['uses-feature'].push({$:{'android:name':'android.hardware.usb.host','android:required':'false'}});
    return cfg;
  });
  config = withMainApplication(config, cfg => {
    let source = cfg.modResults.contents;
    if (!source.includes('add(BilloraPrinterPackage())')) {
      const anchor='PackageList(this).packages.apply {';
      if (!source.includes(anchor)) throw new Error('Review MainApplication registration for this Expo version.');
      source=source.replace(anchor,anchor+'\n              add(BilloraPrinterPackage())');
      source=source.replace(/(package [^\n]+\n)/,'$1\nimport com.billora.printer.BilloraPrinterPackage\n');
      cfg.modResults.contents=source;
    }
    return cfg;
  });
  return withDangerousMod(config,['android',async cfg=>{
    const target=path.join(cfg.modRequest.platformProjectRoot,'app/src/main/java/com/billora/printer');
    fs.mkdirSync(target,{recursive:true});
    fs.copyFileSync(path.join(__dirname,'native/BilloraPrinter.kt'),path.join(target,'BilloraPrinter.kt'));
    return cfg;
  }]);
};
