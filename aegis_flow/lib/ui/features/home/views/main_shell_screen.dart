import 'package:flutter/material.dart';
import '../../../../data/repositories/handover_repository.dart';
import '../../../core/theme.dart';
import '../../../core/widgets/industrial_header.dart';
import '../../field_capture/view_models/field_capture_view_model.dart';
import '../../field_capture/views/field_capture_screen.dart';
import '../../pending_records/view_models/pending_records_view_model.dart';
import '../../pending_records/views/pending_records_screen.dart';
import '../../gemma_assistant/view_models/gemma_assistant_view_model.dart';
import '../../gemma_assistant/views/gemma_assistant_screen.dart';
import '../../scada_telemetry/views/scada_monitor_screen.dart';

class MainShellScreen extends StatefulWidget {
  final HandoverRepository repository;

  const MainShellScreen({
    super.key,
    required this.repository,
  });

  @override
  State<MainShellScreen> createState() => _MainShellScreenState();
}

class _MainShellScreenState extends State<MainShellScreen> {
  int _currentIndex = 0;
  bool _isOffline = true; // Default to offline-first rig state

  late final FieldCaptureViewModel _fieldCaptureViewModel;
  late final PendingRecordsViewModel _pendingRecordsViewModel;
  late final GemmaAssistantViewModel _gemmaAssistantViewModel;

  @override
  void initState() {
    super.initState();
    _fieldCaptureViewModel = FieldCaptureViewModel(repository: widget.repository);
    _pendingRecordsViewModel = PendingRecordsViewModel(repository: widget.repository);
    _gemmaAssistantViewModel = GemmaAssistantViewModel(repository: widget.repository);

    _initData();
  }

  Future<void> _initData() async {
    final offline = await widget.repository.isOfflineMode();
    setState(() {
      _isOffline = offline;
    });
    await _pendingRecordsViewModel.loadRecords();
  }

  void _toggleOffline() async {
    final newStatus = !_isOffline;
    await widget.repository.setOfflineMode(newStatus);
    setState(() {
      _isOffline = newStatus;
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          duration: const Duration(seconds: 2),
          backgroundColor: AegisTheme.surfaceVariant,
          content: Text(
            newStatus
                ? 'Switched to OFFLINE mode (Buffered in SQLite WAL)'
                : 'Switched to ONLINE mode (Cloud Run & Google Storage active)',
            style: TextStyle(
              color: newStatus ? AegisTheme.amberWarning : AegisTheme.successGreen,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
      );
    }
  }

  @override
  void dispose() {
    _fieldCaptureViewModel.dispose();
    _pendingRecordsViewModel.dispose();
    _gemmaAssistantViewModel.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: IndustrialHeader(
        isOffline: _isOffline,
        onToggleOffline: _toggleOffline,
      ),
      body: IndexedStack(
        index: _currentIndex,
        children: [
          FieldCaptureScreen(
            viewModel: _fieldCaptureViewModel,
            onSavedNavigateToRecords: () async {
              await _pendingRecordsViewModel.loadRecords();
              setState(() {
                _currentIndex = 1;
              });
            },
          ),
          PendingRecordsScreen(
            viewModel: _pendingRecordsViewModel,
          ),
          GemmaAssistantScreen(
            viewModel: _gemmaAssistantViewModel,
          ),
          ScadaMonitorScreen(
            sensors: widget.repository.scadaSensors,
            isOffline: _isOffline,
            onToggleOffline: _toggleOffline,
          ),
        ],
      ),
      bottomNavigationBar: ListenableBuilder(
        listenable: _pendingRecordsViewModel,
        builder: (context, _) {
          final offlineCount = _pendingRecordsViewModel.offlineCount;

          return BottomNavigationBar(
            currentIndex: _currentIndex,
            onTap: (index) {
              if (index == 1) {
                _pendingRecordsViewModel.loadRecords();
              }
              setState(() {
                _currentIndex = index;
              });
            },
            items: [
              const BottomNavigationBarItem(
                icon: Icon(Icons.edit_note_rounded),
                label: 'Field Capture',
              ),
              BottomNavigationBarItem(
                icon: Badge(
                  isLabelVisible: offlineCount > 0,
                  label: Text('$offlineCount'),
                  backgroundColor: AegisTheme.amberWarning,
                  textColor: Colors.black,
                  child: const Icon(Icons.sync_alt_rounded),
                ),
                label: 'Records & Sync',
              ),
              const BottomNavigationBarItem(
                icon: Icon(Icons.smart_toy_outlined),
                label: 'Gemma Assistant',
              ),
              const BottomNavigationBarItem(
                icon: Icon(Icons.precision_manufacturing_rounded),
                label: 'SCADA & Architecture',
              ),
            ],
          );
        },
      ),
    );
  }
}
