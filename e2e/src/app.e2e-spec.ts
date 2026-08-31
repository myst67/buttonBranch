import { AppPage } from './app.po';

describe('roster builder', () => {
  let page: AppPage;

  beforeEach(() => {
    page = new AppPage();
  });

  it('shows the title', () => {
    page.navigateTo();
    expect(page.getTitleText()).toEqual('Monthly roster builder');
  });

  it('walks the user through upload, model and build', () => {
    page.navigateTo();
    expect(page.getStepHeadings()).toEqual([
      '1 Last month\'s roster',
      '2 What the model has learned',
      '3 Build the month'
    ]);
  });
});
