import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import '../../../../core/data/handover_repository.dart';
import '../../../../features/report/report_view_model.dart';
import '../../../../features/report/views/report_screen.dart';
import '../../../../features/ask/ask_view_model.dart';
import '../../../../features/ask/views/ask_screen.dart';
import '../../../../features/feed/feed_view_model.dart';
import '../../../../features/feed/views/feed_screen.dart';
import '../../../../features/handover/handover_view_model.dart';
import '../../../../features/handover/views/handover_screen.dart';
import '../../../../core/ai/on_device_ai_service.dart';
import '../../../core/theme.dart';
import '../../../core/widgets/industrial_header.dart';

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
  bool _isOffline = true;

  late final ReportViewModel _reportViewModel;
  late final FeedViewModel _feedViewModel;
  late final HandoverViewModel _handoverViewModel;
  late final AskViewModel _askViewModel;

  @override
  void initState() {
    super.initState();
    _feedViewModel = FeedViewModel(repository: widget.repository);
    _handoverViewModel = HandoverViewModel(repository: widget.repository);
    _askViewModel = AskViewModel(repository: widget.repository);
    _reportViewModel = ReportViewModel(
      repository: widget.repository,
      onSubmitted: () => _feedViewModel.loadFeed(isOnline: !_isOffline),
    );

    _initData();
  }

  Future<void> _initData() async {
    final offline = await widget.repository.isOfflineMode();
    OnDeviceAiService.instance.remoteAllowed = kIsWeb || !offline;
    setState(() {
      _isOffline = offline;
    });
    await _feedViewModel.loadFeed(isOnline: !_isOffline);
  }

  void _toggleOffline() async {
    final newStatus = !_isOffline;
    await widget.repository.setOfflineMode(newStatus);
    OnDeviceAiService.instance.remoteAllowed = kIsWeb || !newStatus;
    setState(() {
      _isOffline = newStatus;
    });
    _feedViewModel.loadFeed(isOnline: !newStatus);
  }

  @override
  void dispose() {
    _reportViewModel.dispose();
    _feedViewModel.dispose();
    _handoverViewModel.dispose();
    _askViewModel.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _feedViewModel,
      builder: (context, _) {
        final pendingCount = _feedViewModel.offlineCount;

        return Scaffold(
          appBar: IndustrialHeader(
            isOffline: _isOffline,
            pendingCount: pendingCount,
            onToggleOffline: _toggleOffline,
            reportViewModel: _reportViewModel,
            onSelectPreset: (presetText) {
              setState(() {
                _currentIndex = 0;
              });
              _reportViewModel.updateTranscript(presetText);
            },
          ),
          body: IndexedStack(
            index: _currentIndex,
            children: [
              ReportScreen(
                viewModel: _reportViewModel,
                isOnline: !_isOffline,
              ),
              FeedScreen(
                viewModel: _feedViewModel,
                isOnline: !_isOffline,
              ),
              HandoverScreen(
                viewModel: _handoverViewModel,
                isOnline: !_isOffline,
              ),
              AskScreen(
                viewModel: _askViewModel,
                isOnline: !_isOffline,
              ),
            ],
          ),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: _currentIndex,
            onTap: (index) {
              FocusManager.instance.primaryFocus?.unfocus(); // a keyboard left open by another tab must not follow you
              if (index == 1) {
                _feedViewModel.loadFeed(isOnline: !_isOffline);
              }
              if (index == 2 && _handoverViewModel.step == HandoverStep.intro) {
                _handoverViewModel.loadShift();
              }
              setState(() {
                _currentIndex = index;
              });
            },
            items: [
              const BottomNavigationBarItem(
                icon: Icon(Icons.mic_none_rounded),
                activeIcon: Icon(Icons.mic_rounded),
                label: 'Report',
              ),
              BottomNavigationBarItem(
                icon: Badge(
                  isLabelVisible: pendingCount > 0,
                  label: Text('$pendingCount'),
                  backgroundColor: AegisTheme.amberWarning,
                  textColor: Colors.black,
                  child: const Icon(Icons.dynamic_feed_outlined),
                ),
                activeIcon: const Icon(Icons.dynamic_feed_rounded),
                label: 'Feed',
              ),
              const BottomNavigationBarItem(
                icon: Icon(Icons.swap_horiz_rounded),
                activeIcon: Icon(Icons.swap_horizontal_circle_rounded),
                label: 'Handover',
              ),
              const BottomNavigationBarItem(
                icon: Icon(Icons.manage_search_rounded),
                activeIcon: Icon(Icons.manage_search_rounded),
                label: 'Ask',
              ),
            ],
          ),
        );
      },
    );
  }
}
