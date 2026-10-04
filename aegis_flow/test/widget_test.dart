import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:aegis_flow/main.dart';
import 'package:aegis_flow/data/repositories/handover_repository.dart';

void main() {
  testWidgets('AegisFlowApp bootstraps and displays Field Capture and Header', (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    final repository = HandoverRepository();

    await tester.pumpWidget(AegisFlowApp(repository: repository));
    await tester.pumpAndSettle();

    // Verify industrial header
    expect(find.text('AEGIS '), findsOneWidget);
    expect(find.text('Flow'), findsOneWidget);

    // Verify Field Capture title
    expect(find.text('1. Field Capture'), findsOneWidget);
    expect(find.text('RECORD OBSERVATION'), findsOneWidget);
  });
}
