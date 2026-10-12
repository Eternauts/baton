import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:archive/archive.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../../../core/data/observation_capsule.dart';
import '../../../ui/core/theme.dart';

class MeshHandoverScreen extends StatelessWidget {
  final List<ObservationCapsule> pendingCapsules;
  final Function(List<ObservationCapsule> receivedCapsules) onReceiveBaton;

  const MeshHandoverScreen({
    super.key,
    required this.pendingCapsules,
    required this.onReceiveBaton,
  });

  String _serializeAndCompress(List<ObservationCapsule> capsules) {
    final jsonString = jsonEncode(capsules.map((c) => c.toMap()).toList());
    final bytes = utf8.encode(jsonString);
    final gzipped = const GZipEncoder().encode(bytes);
    return base64Encode(gzipped);
  }

  List<ObservationCapsule> _decompressAndDeserialize(String payload) {
    final gzipped = base64Decode(payload);
    final bytes = const GZipDecoder().decodeBytes(gzipped);
    final jsonString = utf8.decode(bytes);
    final jsonList = jsonDecode(jsonString) as List;
    return jsonList.map((m) => ObservationCapsule.fromMap(Map<String, dynamic>.from(m))).toList();
  }

  void _showQRScreen(BuildContext context, String payload) {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Scaffold(
        backgroundColor: Colors.white, // Max contrast for scanning
        appBar: AppBar(
          backgroundColor: Colors.white,
          iconTheme: const IconThemeData(color: Colors.black),
          elevation: 0,
          title: const Text('Scan to Receive Baton', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
        ),
        body: Center(
          child: QrImageView(
            data: payload,
            version: QrVersions.auto,
            size: 320,
            backgroundColor: Colors.white,
            errorCorrectionLevel: QrErrorCorrectLevel.M,
          ),
        ),
      ),
    ));
  }

  void _showScannerScreen(BuildContext context) {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Scaffold(
        backgroundColor: Colors.black,
        appBar: AppBar(
          backgroundColor: Colors.black,
          iconTheme: const IconThemeData(color: Colors.white),
          title: const Text('Scan QR Baton', style: TextStyle(color: Colors.white)),
        ),
        body: MobileScanner(
          onDetect: (capture) {
            final List<Barcode> barcodes = capture.barcodes;
            for (final barcode in barcodes) {
              if (barcode.rawValue != null) {
                try {
                  final capsules = _decompressAndDeserialize(barcode.rawValue!);
                  Navigator.pop(context); // Close scanner
                  onReceiveBaton(capsules);
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      backgroundColor: AegisTheme.successGreen,
                      content: Text(
                        'Baton Received: Inherited ${capsules.length} capsules.',
                        style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white, fontSize: 16),
                      ),
                      duration: const Duration(seconds: 4),
                    ),
                  );
                } catch (e) {
                  // Invalid payload
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      backgroundColor: AegisTheme.alertRed,
                      content: Text('Invalid QR code format.', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white)),
                    ),
                  );
                }
              }
            }
          },
        ),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AegisTheme.background,
      appBar: AppBar(
        title: const Text('Offline Mesh Handover'),
      ),
      body: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // PASS BATON
            ElevatedButton.icon(
              onPressed: () {
                if (pendingCapsules.isEmpty) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      backgroundColor: AegisTheme.surfaceVariant,
                      content: Text('No pending capsules to pass.', style: TextStyle(color: AegisTheme.textPrimary)),
                    ),
                  );
                  return;
                }
                final payload = _serializeAndCompress(pendingCapsules);
                _showQRScreen(context, payload);
              },
              style: ElevatedButton.styleFrom(
                minimumSize: const Size.fromHeight(80), // Massive touch target
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(40)), // Pill shape
              ),
              icon: const Icon(Icons.qr_code_2, size: 36, color: Colors.black),
              label: const Text(
                'Pass Baton (Generate QR)',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Share your offline shift log with the incoming operator',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AegisTheme.textMuted),
            ),
            
            const SizedBox(height: 48),
            
            // RECEIVE BATON
            ElevatedButton.icon(
              onPressed: () => _showScannerScreen(context),
              style: ElevatedButton.styleFrom(
                minimumSize: const Size.fromHeight(80),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(40)),
              ),
              icon: const Icon(Icons.document_scanner, size: 36, color: Colors.black),
              label: const Text(
                'Receive Baton (Scan QR)',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Scan a QR code from the outgoing operator\'s device',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AegisTheme.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}
