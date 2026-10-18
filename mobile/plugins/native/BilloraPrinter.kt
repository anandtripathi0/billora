package com.billora.printer

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.*
import android.hardware.usb.*
import android.os.Build
import android.provider.Settings
import android.util.Base64
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.uimanager.ViewManager
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID
import java.util.concurrent.Executors

class BilloraPrinterPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(BilloraPrinter(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

@SuppressLint("MissingPermission")
class BilloraPrinter(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val worker = Executors.newSingleThreadExecutor()
  override fun getName() = "BilloraPrinter"
  private fun usb() = context.getSystemService(Context.USB_SERVICE) as UsbManager
  private fun bluetooth() = (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
  private fun readyBluetooth() = (bluetooth() ?: throw Exception("This phone has no Bluetooth adapter.")).also {
    check(it.isEnabled) {"Bluetooth is off. Turn it on in Android Bluetooth settings."}
  }
  // Every operation uses a fresh connection. Never retain a stale 'connected' flag.
  private fun withBluetooth(address: String, action: (BluetoothSocket) -> Unit) {
    val adapter=readyBluetooth()
    val device=adapter.bondedDevices.firstOrNull {it.address.equals(address, ignoreCase=true)}
      ?: throw Exception("Printer is not paired. Pair it in Android Bluetooth settings, then refresh the list.")
    val socket=device.createRfcommSocketToServiceRecord(UUID.fromString("00001101-0000-1000-8000-00805F9B34FB"))
    val watchdog=Thread {try {Thread.sleep(20000);socket.close()} catch (_: Exception) {}}
    watchdog.isDaemon=true;watchdog.start()
    try {socket.connect();action(socket)}
    finally {watchdog.interrupt();try {socket.close()} catch (_: Exception) {}}
  }
  @ReactMethod fun bluetoothStatus(promise: Promise) {
    try {
      val adapter=bluetooth();val result=Arguments.createMap()
      result.putBoolean("available",adapter!=null);result.putBoolean("enabled",adapter?.isEnabled==true)
      promise.resolve(result)
    } catch(e: Exception) {promise.reject("BLUETOOTH", "Allow Nearby devices permission in Android app settings.")}
  }
  @ReactMethod fun checkBluetooth(address: String, promise: Promise) {
    worker.execute {
      try {withBluetooth(address) {};promise.resolve(true)}
      catch(e: Exception) {promise.reject("CONNECT", "${e.message} Turn on the printer, keep it nearby and disconnect other phones using it. Only Bluetooth Classic SPP printers are supported.")}
    }
  }
  @ReactMethod fun pair(promise: Promise) {
    try {context.startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); promise.resolve(true)}
    catch (e: Exception) {promise.reject("PAIR", "Open Android Bluetooth settings manually.")}
  }
  @ReactMethod fun devices(transport: String, promise: Promise) {
    try {
      val out = Arguments.createArray()
      if (transport == "bluetooth") readyBluetooth().bondedDevices.forEach { d ->
        val item=Arguments.createMap();item.putString("name",d.name ?: "Paired printer");item.putString("address",d.address);out.pushMap(item)
      }
      if (transport == "usb") usb().deviceList.values.forEach { d ->
        val item=Arguments.createMap();item.putString("name",d.productName ?: "USB device");item.putString("address",d.deviceName);out.pushMap(item)
      }
      promise.resolve(out)
    } catch (e: Exception) {promise.reject("DEVICES", e.message ?: "Cannot list printers. Check Android permissions.")}
  }
  @ReactMethod fun print(transport: String, address: String, base64: String, promise: Promise) {
    worker.execute {
      try {
        val bytes=Base64.decode(base64,Base64.DEFAULT)
        require(bytes.size <= 262144) {"Print job too large."}
        when (transport) {
          "lan" -> {
            require(address.matches(Regex("(?:[0-9]{1,3}\\.){3}[0-9]{1,3}"))) {"Enter a printer IPv4 address."}
            require(address.split('.').all {it.toInt() in 0..255}) {"Invalid IPv4 address."}
            Socket().use { socket ->
              val watchdog=Thread {try {Thread.sleep(20000);socket.close()} catch (_: Exception) {}}
              watchdog.isDaemon=true;watchdog.start()
              try {
                socket.connect(InetSocketAddress(address,9100),10000);socket.soTimeout=10000
                socket.getOutputStream().write(bytes);socket.getOutputStream().flush()
              } finally {watchdog.interrupt()}
            }
          }
          "bluetooth" -> {
            withBluetooth(address) {socket -> socket.outputStream.write(bytes);socket.outputStream.flush()}
          }
          "usb" -> {
            val manager=usb();val device=manager.deviceList[address] ?: throw Exception("USB printer is not connected.")
            if (!manager.hasPermission(device)) {
              val intent=PendingIntent.getBroadcast(context,0,Intent(context.packageName+".USB_PERMISSION").setPackage(context.packageName),PendingIntent.FLAG_IMMUTABLE)
              manager.requestPermission(device,intent)
              throw Exception("Approve the Android USB permission prompt, then retry once. No bytes were sent.")
            }
            var found: Pair<UsbInterface,UsbEndpoint>?=null
            for (i in 0 until device.interfaceCount) {
              val face=device.getInterface(i)
              for (j in 0 until face.endpointCount) {
                val endpoint=face.getEndpoint(j)
                if (endpoint.type==UsbConstants.USB_ENDPOINT_XFER_BULK && endpoint.direction==UsbConstants.USB_DIR_OUT) found=Pair(face,endpoint)
              }
            }
            val (face,endpoint)=found ?: throw Exception("No compatible USB bulk OUT endpoint.")
            val connection=manager.openDevice(device) ?: throw Exception("Cannot open USB printer.")
            try {
              require(connection.claimInterface(face,true)) {"Printer interface is busy."}
              var offset=0
              while(offset<bytes.size) {
                val count=connection.bulkTransfer(endpoint,bytes,offset,minOf(4096,bytes.size-offset),10000)
                require(count>0) {"USB result uncertain. Check paper before retrying."};offset+=count
              }
              connection.releaseInterface(face)
            } finally {connection.close()}
          }
          else -> throw Exception("Unsupported printer transport.")
        }
        promise.resolve(true)
      } catch(e: Exception) {promise.reject("PRINT", e.message ?: "Print failed. Check physical output before retrying.")}
    }
  }
}
