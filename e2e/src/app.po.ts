import { browser, by, element } from 'protractor';

export class AppPage {
  navigateTo() {
    return browser.get('/');
  }

  getTitleText() {
    return element(by.css('app-root h1')).getText();
  }

  getStepHeadings() {
    return element.all(by.css('app-root .panel-head h2')).getText();
  }
}
