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
import 'services/api_service.dart';

void main() {
  final apiService = ApiService();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => SettingsProvider(apiService)),
        ChangeNotifierProvider(create: (_) => DashboardProvider(apiService)),
        ChangeNotifierProvider(create: (_) => TradeProvider(apiService)),
        ChangeNotifierProvider(create: (_) => PortfolioProvider(apiService)),
        ChangeNotifierProvider(create: (_) => RiskProvider(apiService)),
        ChangeNotifierProvider(create: (_) => MandateProvider(apiService)),
        ChangeNotifierProvider(create: (_) => FactorProvider(apiService)),
        ChangeNotifierProvider(create: (_) => StrategyProvider(apiService)),
        ChangeNotifierProvider(create: (_) => KnowledgeProvider(apiService)),
      ],
      child: const TsarApp(),
    ),
  );
}
