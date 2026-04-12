## Mobile Validation Checklist

### Device targets
- iPhone SE (small)
- iPhone 12/13/14 (standard)
- Samsung Galaxy S21 (Android)

### Browsers
- iOS Safari
- Android Chrome
- Android Firefox

### Layout checks (all tabs)
- Tile spacing: 8–16px between cards/sections
- Text: body text at least 14px equivalent, no vertical “letter stacking”
- Buttons: all interactive elements at least 44×44px
- Links: fund/ETF names are tappable and open the performance detail page
- Scrolling: no jitter, smooth scroll to anchors, bottom nav doesn’t hide content

### DevTools emulation (Chrome)
1. Open DevTools → Toggle device toolbar
2. Test iPhone SE + iPhone 12 presets
3. Throttle network: “Fast 3G” and “Slow 3G”
4. Reload each tab and watch for layout shifts and overflow

### Performance (Lighthouse)
1. DevTools → Lighthouse
2. Mode: Mobile
3. Network: Simulated Slow 4G (or use “Slow 3G” in Network tab for harsher test)
4. Record:
   - Performance score
   - LCP
   - Total Blocking Time
   - CLS

### Screenshot capture
- Capture “before” and “after” for:
  - Overview cards
  - Accounts list and account detail actions
  - Budget tiles and inputs
  - Monthly Update checklist + holding rows
