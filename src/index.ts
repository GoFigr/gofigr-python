
import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import {
  INotebookTracker,
  Notebook,
  NotebookPanel
} from '@jupyterlab/notebook';
import {IComm, IKernelConnection} from "@jupyterlab/services/lib/kernel/kernel";

import * as packageData from '../package.json';

// Declare a WeakMap to store state specific to each NotebookPanel
interface ICustomNotebookState {
  kernel: IKernelConnection | null;
  comm: IComm | null
}

import { JSONObject } from '@lumino/coreutils';

interface IGofigrMessage extends JSONObject {
  url: string;
  notebook_path: string;
  notebook_local_path: string;
  title: string;
  extension_version: string;
}

const notebookState = new WeakMap<NotebookPanel, ICustomNotebookState>();

function getGoFigrMessage(panel: NotebookPanel): IGofigrMessage {
  return {
    url: document.URL,
    notebook_path: panel.context.path,
    notebook_local_path: panel.context.localPath,
    title: panel.title.label,
    extension_version: packageData.version
  }
}

function sendGoFigrMessage(panel: NotebookPanel): void {
  const state = notebookState.get(panel);
  const msg = getGoFigrMessage(panel);

  if (state && state.comm) {
    state.comm.send(msg);
  }
}


/**
 * Initialization data for the my-extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'gofigr:plugin',
  description: 'A JupyterLab extension that watches for cell execution',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (app: JupyterFrontEnd, tracker: INotebookTracker) => {
    console.log('JupyterLab GoFigr extension active');


    // Function to attach cell execution watcher to a notebook panel
    const watchCellExecution = (panel: NotebookPanel): void => {
      // Listen for the executed signal on the notebook content

       if (!notebookState.has(panel)) {
        notebookState.set(panel, {
          kernel: null,
          comm: null
        });
      }

      panel.sessionContext.kernelChanged.connect((sender, args) => {
          console.log(`Kernel started/restarted for notebook at path: ${panel.context.path}`);

          const newKernel = args.newValue;
          newKernel?.registerCommTarget("gofigr", (comm: any, msg: any) => {
            console.log("Kernel Comm established. Message: ", msg);
            notebookState.set(panel, {
              comm: comm,
              kernel: newKernel});
            console.log(notebookState.get(panel)?.comm?.commId);
            sendGoFigrMessage(panel);
          })
        })

      panel.content.stateChanged.connect((sender: Notebook, args: any) => {
        sendGoFigrMessage(panel)
      })
    }

    // Apply watcher to all existing notebook panels
    tracker.forEach((panel: NotebookPanel) => {
      watchCellExecution(panel);
    });

    // Apply watcher to any new notebook panels
    tracker.widgetAdded.connect((sender: any, panel: NotebookPanel) => {
      watchCellExecution(panel);
    });
  }
};

export default plugin;
