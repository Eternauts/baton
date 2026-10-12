import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:aegis_flow/main.dart';
import 'package:aegis_flow/core/data/handover_repository.dart';
import 'package:aegis_flow/ui/core/widgets/baton_logo.dart';
import 'package:aegis_flow/ui/core/widgets/baton_splash.dart';

void main() {
  testWidgets('BatonApp bootstraps and displays Report screen and Header', (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    final repository = HandoverRepository();

    await tester.pumpWidget(BatonApp(repository: repository));
    expect(find.byType(BatonSplash), findsOneWidget); // the animated B opens the app

    await tester.pump(const Duration(seconds: 3)); // splash runs 2.4 s, then fades
    await tester.pumpAndSettle();
    expect(find.byType(BatonSplash), findsNothing);

    // Verify header: the Baton lockup, not the old AEGIS Flow text
    expect(find.byType(BatonLockup), findsOneWidget);
    expect(find.text('AEGIS Flow'), findsNothing);

    // Verify Report Screen
    expect(find.text('Tap and describe what you see'), findsOneWidget);
    expect(find.text('Report'), findsOneWidget);
    expect(find.text('Feed'), findsOneWidget);
  });
}
