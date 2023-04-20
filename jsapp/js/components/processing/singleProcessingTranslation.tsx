import React, {useState} from 'react';
import {formatTime} from 'js/utils';
import singleProcessingStore, {
  SingleProcessingTabs,
} from 'js/components/processing/singleProcessingStore';
import type {Transx} from 'js/components/processing/singleProcessingStore';
import TransxSelector from './transxSelector';
import styles from './singleProcessingPreview.module.scss';
import bodyStyles from './processingBody.module.scss';
import {AsyncLanguageDisplayLabel} from 'js/components/languages/languagesUtils';
import type {LanguageCode} from 'js/components/languages/languagesStore';

interface SingleProcessingTranslationProps {
  singleTransx: Transx;
}

export default function SingleProcessingTranslation(props: SingleProcessingTranslationProps) {
  const [store] = useState(() => singleProcessingStore);

  function renderLanguageAndDate() {
    const source = props.singleTransx;

    const contentLanguageCode = source?.languageCode;
    if (contentLanguageCode === undefined) {
      return null;
    }

    let dateText = '';
    if (source) {
      if (source.dateCreated !== source?.dateModified) {
        dateText = t('last modified ##date##').replace(
          '##date##',
          formatTime(source.dateModified)
        );
      } else {
        dateText = t('created ##date##').replace(
          '##date##',
          formatTime(source.dateCreated)
        );
      }
    }

    return (
      <React.Fragment>
        <AsyncLanguageDisplayLabel code={props.singleTransx.languageCode} />

        {dateText !== '' && (
          <time className={bodyStyles.transxHeaderDate}>{dateText}</time>
        )}
      </React.Fragment>
    );
  }

  return (
    <section className={styles.root}>
      <div className={bodyStyles.root}>
        <header className={bodyStyles.transxHeader}>
          {renderLanguageAndDate()}
        </header>

        <article className={bodyStyles.text}>
          {props.singleTransx.value}
        </article>
      </div>
    </section>
  );
}

