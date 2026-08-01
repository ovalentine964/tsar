import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'app.dart';
import 'providers/dashboard_provider.dart';
import 'providers/trade_provider.dart';
import 'providers/portfolio_provider.dart';
import 'providers/risk_provider.dart';
import 'providers/mandate_provider.dart';
import 'providers/factor_provider.dart';
import 'providers/strategy_provider.dart';
import 'providers/knowledge_provider.dart';
import 'providers/settings_provider.dart';
import 'providers/news_provider.dart';
import 'providers/signal_quality_provider.dart';
import 'providers/defi_provider.dart';
import 'providers/blockchain_provider.dart';
import 'services/api_service.dart';
import 'services/websocket_service.dart';
import 'services/notification_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final apiService = ApiService();
  final wsService = WebSocketService(apiService);
  final notificationService = NotificationService();

  // Initialize notifications (non-blocking)
  notificationService.initialize();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => SettingsProvider(apiService)),
        ChangeNotifierProvider(create: (_) => DashboardProvider(apiService)),
        ChangeNotifierProvider(create: (_) => TradeProvider(apiService)),
        ChangeNotifierProvider(create: (_) => PortfolioProvider(apiService)),
        ChangeNotifierProvider(create: (_) => RiskProvider(apiService, notificationService)),
        ChangeNotifierProvider(create: (_) => MandateProvider(apiService)),
        ChangeNotifierProvider(create: (_) => FactorProvider(apiService)),
        ChangeNotifierProvider(create: (_) => StrategyProvider(apiService)),
        ChangeNotifierProvider(create: (_) => KnowledgeProvider(apiService)),
        ChangeNotifierProvider(create: (_) => NewsProvider(apiService)),
        ChangeNotifierProvider(create: (_) => SignalQualityProvider(apiService)),
        ChangeNotifierProvider(create: (_) => DeFiProvider(apiService)),
        ChangeNotifierProvider(create: (_) => BlockchainProvider(apiService)),
        Provider.value(value: wsService),
        Provider.value(value: notificationService),
      ],
      child: const TsarApp(),
    ),
  );
}
