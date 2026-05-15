// Tooltip açıklamaları — kısaltmalar ve teknik terimler

export const TOOLTIPS: Record<string, string> = {
  // Feature kısaltmaları
  "rsi_14": "Relative Strength Index — 14 haftalık. 70+ aşırı alım, 30- aşırı satım.",
  "macd": "Moving Average Convergence Divergence — trend dönüş sinyali.",
  "macd_signal": "MACD sinyal hattı — 9 periyotluk EMA of MACD.",
  "macd_hist": "MACD histogram — MACD ile sinyal hattı farkı.",
  "sma_20": "Simple Moving Average 20 hafta — kısa vadeli ortalama.",
  "sma_50": "Simple Moving Average 50 hafta — orta vadeli trend.",
  "sma_200": "Simple Moving Average 200 hafta — uzun vadeli trend.",
  "ema_12": "Exponential Moving Average 12 hafta — ağırlıklı ortalama.",
  "ema_26": "Exponential Moving Average 26 hafta — MACD hesabında kullanılır.",
  "bb_position": "Bollinger Bands pozisyonu — fiyatın bant içindeki yeri (-1 ile +1).",
  "atr_14": "Average True Range 14 hafta — volatilite ölçüsü.",
  "volume_zscore": "Hacim Z-skoru — ortalama hacimden ne kadar sapma.",
  "return_1w": "1 haftalık getiri — geçen hafta yüzde değişim.",
  "return_4w": "4 haftalık getiri — son 1 ay yüzde değişim.",
  "return_12w": "12 haftalık getiri — son 3 ay yüzde değişim.",
  "momentum": "Momentum — fiyat değişim hızı.",
  "high_52w_distance": "52 hafta zirvesine uzaklık — ne kadar geride (%).",
  "low_52w_distance": "52 hafta dibine uzaklık — ne kadar yukarıda (%).",
  "trend_strength": "Trend gücü — ADX benzeri trend ölçüsü.",
  "price_to_sma50": "Fiyat / SMA50 oranı — 1.0 üstü yükseliş trendi.",
  "price_to_sma200": "Fiyat / SMA200 oranı — 1.0 üstü boğa piyasası.",
  "realized_vol": "Realize Volatilite — son 12 hafta standart sapma.",
  
  // Finansal feature'lar
  "pe_ratio": "Fiyat/Kazanç oranı — hisse başına ne kadar ödeniyor.",
  "forward_pe": "İleri tarihli P/E — gelecek yıl tahmini kazanç bazlı.",
  "price_to_sales": "Fiyat/Satış oranı — şirket değeri / gelir.",
  "price_to_book": "Fiyat/Defter değeri — varlıklara göre değerleme.",
  "ev_to_ebitda": "Kurumsal Değer / EBITDA — borç dahil değerleme.",
  "gross_margin": "Brüt kar marjı — satıştan ne kadar kar kalıyor (%).",
  "operating_margin": "Faaliyet kar marjı — operasyonel karlılık (%).",
  "net_margin": "Net kar marjı — son karlılık (%).",
  "roe": "Return on Equity — öz sermaye getirisi (%).",
  "roa": "Return on Assets — aktif getirisi (%).",
  "revenue_growth": "Gelir büyümesi — yıllık gelir artışı (%).",
  "earnings_growth": "Kazanç büyümesi — yıllık kar artışı (%).",
  "debt_to_equity": "Borç/Öz sermaye oranı — finansal kaldıraç.",
  "current_ratio": "Cari oran — kısa vadeli ödeme gücü.",
  "beta": "Beta — piyasa duyarlılığı (1.0 = piyasa ile aynı).",
  
  // Makro feature'lar
  "VIX": "Volatilite Endeksi — piyasa korku ölçüsü (20+ yüksek).",
  "VIX_WEEKLY": "Haftalık VIX değişimi.",
  "VIX_CHANGE_W": "VIX haftalık değişim yüzdesi.",
  "TNX_10Y": "10 yıllık Hazine tahvili faizi — risk-free rate proxy.",
  "FED_RATE_PROXY": "Fed fonlama faizi proxy'si.",
  "RISK_ON_SCORE": "Risk-on skoru — yatırımcı risk iştahı.",
  "sp500_trend_20w": "S&P500 20 haftalık trend yönü.",
  "nasdaq_trend_20w": "NASDAQ 20 haftalık trend yönü.",
  "cpi_proxy_trend_26w": "CPI proxy 26 haftalık trend — enflasyon göstergesi.",
  
  // Haber/Sosyal
  "news_sentiment_score": "Haber duygu skoru (-1 negatif, +1 pozitif).",
  "news_volume": "Haber hacmi — kaç haber çıktı.",
  "news_earnings_flag": "Kazanç haberi bayrağı — bu hafta kazanç var mı.",
  "social_mention_count": "Sosyal medya mention sayısı.",
  "social_mention_momentum": "Sosyal mention momentumu — artış/azalış.",
  "social_sentiment_polarity": "Sosyal medya duygu polaritesi.",
  
  // Diğer
  "pe_percentile_sector": "P/E sektör yüzdeliği — sektör içinde ne kadar ucuz/pahalı.",
  "pb_percentile_sector": "P/B sektör yüzdeliği.",
  "ev_ebitda_percentile_sector": "EV/EBITDA sektör yüzdeliği.",
  "alpha_alignment": "Alpha uyumu — model tahmini ile gerçekleşme uyumu.",
  "alpha_factor_1": "Alpha faktörü 1 — istatistiksel anomali göstergesi.",
  "alpha_factor_2": "Alpha faktörü 2 — momentum tabanlı alpha.",
  "alpha_factor_3": "Alpha faktörü 3 — değerleme tabanlı alpha.",
  "anchor_breakout_signal": "Ankor kırılım sinyali — önemli direnç destek kırılımı.",
  "anchor_proximity_high": "Yakın zirve mesafesi — ne kadar yakın.",
  "anchor_proximity_low": "Yakın dip mesafesi — ne kadar yakın.",
  "bab_score": "Bet Against Beta skoru — düşük beta hisselerini seçme eğilimi.",
  "beta_52w": "52 haftalık beta — 1 yıllık piyasa duyarlılığı.",
  "beta_percentile_in_sector": "Beta sektör yüzdeliği.",
  "combined_momentum": "Birleşik momentum — çoklu momentum göstergesi.",
  "days_since_last_earnings": "Son kazanç açıklamasından bu yana geçen gün.",
  "days_to_cover": "Kısa pozisyon kapatma süresi — short interest / günlük hacim.",
  "days_to_next_earnings": "Sonraki kazanç açıklamasına kalan gün.",
  "drift_momentum": "Sürüklenme momentumu — yavaş ama sürekli trend.",
  
  // Model tipleri
  "lightgbm": "LightGBM — Microsoft'un hızlı gradient boosting algoritması.",
  "logistic_regression": "Lojistik Regresyon — basit olasılık modeli.",
  "random_forest": "Random Forest — çoklu karar ağacı ensemble.",
  "gradient_boosting": "Gradient Boosting — hata düzeltme ile boosting.",
  "catboost": "CatBoost — Yandex'in kategorik veri dostu boosting'i.",
  "xgboost": "XGBoost — eXtreme Gradient Boosting — en popüler ML kütüphanesi.",
  "neural_network": "Yapay Sinir Ağı — derin öğrenme modeli.",
  
  // Hedef değişkenler
  "target_2pct_1w": "Hedef: 1 haftada ≥%2 getiri — ikili sınıflandırma.",
  "target_3pct_1w": "Hedef: 1 haftada ≥%3 getiri — ikili sınıflandırma.",
  "risk_target_1w": "Hedef: 1 haftada ≤-%2 kayıp — risk sınıflandırması.",
  
  // Pipeline butonları
  "Evren Snapshot": "Seçili hisseleri veritabanına kaydet ve evreni güncelle.",
  "Fiyat Al": "Yahoo Finance'dan güncel fiyat verisi çek.",
  "Feature Hesapla": "Teknik göstergeleri ve istatistiksel feature'ları hesapla.",
  "Makro (VIX/Faiz)": "VIX, faiz oranları, enflasyon gibi makro verileri çek.",
  "Haberler": "Finansal haberleri ve duygu analizini çek.",
  "Finansallar": "Şirket finansal verilerini (P/E, marjlar vb.) çek.",
  "Bilanço/Gelir/NA": "Bilanço, gelir tablosu, nakit akışı verilerini çek.",
  "Sosyal Duygu": "Twitter/Reddit sosyal medya duygu analizini çek.",
  "Tümünü Çalıştır": "Tüm pipeline adımlarını sırayla çalıştır.",
  
  // Backtest terimleri
  "Sharpe": "Sharpe Oranı — risk düzeltilmiş getiri (0.5+ iyi).",
  "Deflated SR": "Deflated Sharpe — çoklu test düzeltmeli Sharpe.",
  "Win Rate": "Kazanma oranı — pozitif getiri oranı (%).",
  "Max DD": "Maximum Drawdown — en büyük düşüş (%).",
  "Permütasyon p": "Permütasyon testi p-değeri — şans olasılığı (<0.10 anlamlı).",
  "SPY Sharpe": "S&P500 ETF Sharpe oranı — benchmark karşılaştırması.",
  "Benchmark Alpha": "Benchmark üstü getiri — piyasa dışı kazanç.",
  "Walk-Forward": "Zaman serisi cross-validation — geleceği tahmin etme simülasyonu.",
  "Fold": "Test dönemi parçası — walk-forward'un bir segmenti.",
  
  // Genel terimler
  "Kill Switch": "Acil durum durdurucu — sistem performansı düşerse otomatik devreye girer.",
  "Paper Trade": "Sanal işlem — gerçek para kullanmadan test.",
  "Hit Rate": "Başarı oranı — hedeflenen getiriyi yakalama oranı.",
  "Kalibrasyon Hatası": "Tahmin olasılığı ile gerçekleşme arası fark.",
  "Likidite Filtresi": "Günlük $5M+ hacim şartı — düşük hacimli hisseleri ele.",
  "Eşik": "Tahmin olasılığı eşiği — bu değer üstü hisseler seçilir.",
  "Holding": "Pozisyon tutma süresi — kaç hafta hisseyi tut.",
  "Max Pozisyon": "Aynı anda en fazla kaç hisse seçilecek.",
  "Promoted": "Onaylanmış strateji — kabul kapısından geçmiş.",
  "Candidate": "Aday strateji — test aşamasında.",
  "P(≥%2)": "1 haftada %2 ve üzeri getiri olasılığı.",
  "P(≤-%2)": "1 haftada %2 ve üzeri kayıp olasılığı.",
  "Beklenen Getiri": "Modelin tahmini ortalama getirisi.",
  "Güven": "Model güven seviyesi — yüksek/orta/düşük.",
};

export function getTooltip(key: string): string | undefined {
  return TOOLTIPS[key];
}
