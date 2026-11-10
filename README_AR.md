# AI CAR CLIP SORTER PRO — Mac Intel

## الوظائف
- تقسيم الفيديو إلى مشاهد باستخدام PySceneDetect (Content + Adaptive).
- التحكم في حساسية الكشف وأقصر مدة للمشهد.
- تصدير المقاطع بصيغة MP4 إلى ClipsCars.
- مشغل تلقائي Loop لعرض مقاطع ClipsCars.
- تصنيف MovingCars / StoppingCars / ExcludedCars.
- تجاوز مؤقت، إعادة المقاطع المتجاوزة، تراجع عن آخر تصنيف.
- إحصائيات وعدّادات للمجلدات.
- حفظ الحالة محلياً في Application Support.

## مجلدات العمل
افتراضياً:
`~/Movies/AI CAR CLIP SORTER/`
ويتم إنشاء:
- ClipsCars
- MovingCars
- StoppingCars
- ExcludedCars

يمكن تغيير مجلد العمل من داخل التطبيق.

## البناء المجاني عبر GitHub Actions
1. أنشئ مستودعاً جديداً أو حدّث مستودعك الحالي.
2. ارفع `main.py` و`requirements.txt` ومجلد `.github/workflows/build.yml`.
3. افتح Actions ثم Build Mac Intel App ثم Run workflow.
4. بعد نجاح البناء، حمّل Artifact باسم `AI-CAR-CLIP-SORTER-PRO-MAC-INTEL`.
5. فك ZIP وانقل التطبيق إلى Applications.

ملاحظة: هذه نسخة أولية لإعادة بناء الوظائف الأساسية على macOS Intel. يجب اختبارها على جهازك قبل اعتبارها إصداراً نهائياً. قد يمنع Gatekeeper فتح التطبيق أول مرة لأن الحزمة غير موقعة/موثقة من Apple.
